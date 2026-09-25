# L3B Architecture Record

Mô tả kiến trúc của bản v5 (điểm public 92.91). Code: `src/student_agent/workflow.py` (`solve_case`, `_bundles`, `_detect`) và `src/student_agent/mcp_gateway.py`. Quá trình đi từ v1 đến v5 và lý do của từng quyết định được ghi trong `EXPERIMENTS.md`.

Hệ thống không dùng LLM. Mỗi "agent" là một vai trò trong code Python, giao việc cho nhau theo một pipeline cố định; mọi quyết định là luật tất định và tra bảng policy.

## 1. System overview

```text
inputs/<case>.json
   │
   ▼
coordinator ──task_assigned──► entity-agent ─── get_order, get_customer_history
   │                               │  (cả hai lỗi → dừng cả lần chạy)
   │◄──────────handoff─────────────┘
   ├──task_assigned──► order-agent ─── get_order_items, get_product_context*
   ├──task_assigned──► shipment-agent ─── get_shipment_summary      (topic giao hàng)
   ├──task_assigned──► payment-agent ─── get_payment_timeline, get_refund_timeline*
   │                                                                  (topic thanh toán / hoàn tiền)
   └──task_assigned──► policy-agent ─── get_policy
                          │
                          ▼
              conflict resolver (trong code, không gọi MCP)
              tách lần mua → bỏ lần mua sau opened_at → chọn lần mua khớp topic
                          │
                    policy_decided
                          ▼
                       verifier ──verification_completed──► outputs/<case>.json

Mọi bước ghi vào traces/trace.jsonl. Mọi MCP call đi qua EvidenceGateway (audit + snapshot).
* product bỏ qua với refund_*; refund chỉ gọi với refund_*.
```

Mỗi case dùng đúng **6 MCP call**: 4 call cố định (order, customer_history, order_items, policy) và 2 call theo nhóm topic.

## 2. Agent ownership

| Actor | Input | Trách nhiệm | Tool permission | Output/handoff |
| --- | --- | --- | --- | --- |
| Entity/customer (`entity-agent`) | `claimed_order_id`, `candidate_order_ids`, `customer_unique_id_hint` | Xác nhận đơn thật, loại candidate không có trong lịch sử khách, lấy các dòng order của khách | `get_order`, `get_customer_history` | Đơn resolved/rejected, các dòng order → coordinator |
| Coordinator (`coordinator`) | File case | Đọc topic, giao việc theo nhóm topic, nhận kết quả | Không gọi tool | `task_assigned` cho từng agent |
| Order/product (`order-agent`) | `order_id` | Lấy item, seller, giá, phí ship, hạn bàn giao; danh mục sản phẩm khi scope yêu cầu | `get_order_items`, `get_product_context` (không gọi với refund_*) | Items → coordinator |
| Shipment (`shipment-agent`) | `order_id` | Mốc giao hàng và sự kiện giao trễ | `get_shipment_summary`; chỉ chạy với `late_delivery_*`, `unsupported_claim` | Shipment → coordinator |
| Payment/refund (`payment-agent`) | `order_id` | Các dòng thanh toán, sự kiện capture/mismatch; sự kiện hoàn tiền | `get_payment_timeline` (7 topic thanh toán/hoàn tiền); `get_refund_timeline` (chỉ `refund_*`) | Payment, refund → coordinator |
| Policy (`policy-agent`) | `policy_version` | Tra `rules[primary_issue]`: status, action, số tiền hoàn, loại bên chịu trách nhiệm | `get_policy` | `policy_decided` → verifier |
| Conflict resolver (trong `solve_case`) | Các dòng order, items, events | Tách hai lần mua, loại lần mua mồi, chọn lần mua khớp topic, ghi `data_conflicts` | Không gọi tool | Lần mua "focus" cho policy và output |
| Verifier (`verifier`) | Output đã ghép | Kiểm tra bất biến trước khi xuất | Không gọi tool | `verification_completed` → coordinator |

Least privilege: mỗi agent chỉ gọi tool của domain mình, và chỉ khi topic cần. Gọi tool của domain không liên quan vừa làm giảm độ chính xác evidence vừa vượt ngân sách call.

## 3. Entity resolution và A2A protocol

**Entity resolution.**
- Tập đơn "đã biết" = mọi `order_id` trong `get_customer_history` cộng `claimed_order_id` nếu `get_order` trả kết quả.
- Candidate nằm trong tập đó → `resolved_order_ids`; còn lại → `rejected_candidates`. Placeholder `candidate-XXX` không bao giờ được gọi MCP (tiết kiệm call, và không tồn tại trong lịch sử khách).
- `status`: 1 đơn resolved → `resolved` (confidence 0.95); nhiều → `ambiguous` (0.3); không có → `not_found` (0.3).
- `customer_unique_id_hint` được dùng trực tiếp làm tham số `get_customer_history`.

**Kết luận chính.** `primary_issue` = topic của claim đầu tiên, nếu policy có luật cho topic đó; nếu không có lần mua hợp lệ hoặc không có luật thì `insufficient_evidence`. Quyết định này dựa trên bằng chứng từ điểm public: tự suy luận kết luận (v1) cho semantic 84.07, tin topic cho 90.92. Rủi ro còn lại: nếu tập private có topic sai, code không tự sửa kết luận (ghi trong `EXPERIMENTS.md`).

**Message envelope.** Giao tiếp giữa các agent là lời gọi hàm trong cùng tiến trình; mỗi lần giao nhận được ghi thành một trace event theo `contracts/schemas/trace-event-v1.schema.json`:

| Event | actor → target | Khi nào |
| --- | --- | --- |
| `case_received` | coordinator | CLI bắt đầu case |
| `task_assigned` | coordinator → agent | Trước khi agent chạy |
| `tool_result_consumed` | agent (kèm `tool_name`, `evidence_refs`) | Sau mỗi call thành công |
| `handoff` | agent → coordinator | Agent trả kết quả |
| `policy_decided` | policy-agent → verifier (`decision_code` = action) | Sau khi tra policy |
| `verification_completed` | verifier → coordinator (`decision_code` = `issue:status`) | Sau khi kiểm tra |
| `case_finalized` | coordinator | CLI ghi output xong |

**Correlation.** Mọi event và mọi MCP call mang `case_id` của case đang xử lý. Mỗi case có một `_Investigation` riêng (ref, domain, cache), tạo mới cho từng case nên không có dữ liệu lọt sang case khác.

**Handoff, timeout, vòng lặp.** Pipeline tuyến tính, không có vòng lặp: entity → order → shipment/payment (tùy topic) → policy → verifier. Timeout HTTP do gateway đặt: đọc 300 giây, kết nối/ghi/pool 30 giây. Trace chỉ ghi sự kiện quan sát được, không ghi suy luận.

## 4. Evidence và conflict lifecycle

1. **Validate.** `EvidenceGateway.call` kiểm tra mỗi response theo `mcp-evidence-response-v1.schema.json` trước khi trả về. Response lỗi (`is_error`) thành `RuntimeError`.
2. **Lưu ref.** `_Investigation.get` lưu `evidence_ref` theo tool và theo `domain`, rồi emit `tool_result_consumed` với đúng ref đó. Ref được chép nguyên văn, không bao giờ tự tạo hay sửa.
3. **Snapshot.** Khi chạy qua CLI, mọi response (kể cả lỗi) được ghi vào `data/mcp_samples/<case_id>/<tool>.json` để thử luật offline (`data/replay.py`). Lỗi không ghi đè snapshot tốt.
4. **Tách lần mua (`_bundles`).** Dữ liệu của một `order_id` chứa hai lần mua trộn lẫn. Các dòng order trong lịch sử khách được xếp theo ngày mua; mỗi lần mua sở hữu khoảng [ngày mua, ngày mua kế tiếp). Item được gán theo `shipping_limit_date`, sự kiện payment/shipment theo `event_at`.
5. **Loại mồi.** Lần mua có ngày mua sau `opened_at` bị loại (không thể khiếu nại đơn chưa mua). Sự kiện refund sau `opened_at` cũng bị bỏ.
6. **Chọn lần mua focus.** `_detect` chạy luật trên từng lần mua còn lại; lần mua gần nhất có dấu hiệu khớp topic là focus. Không có thì dùng lần mua gần nhất trước `opened_at`. Focus cung cấp `item_ids`, `seller_ids` và seller cho `responsible_parties`.
7. **Source precedence.** Lịch sử khách (đủ các lần mua) được ưu tiên hơn `get_order` (chỉ trả một dòng, có thể là lần mua mồi). Khi hai nguồn khác nhau, ghi `data_conflicts`: `field=order_timeline`, `sources=[get_order, get_customer_history]`, `selected_source=get_customer_history`, `resolution_code=PURCHASE_IN_SCOPE_OF_CASE`.
8. **Map evidence vào output.** `evidence_refs` = mọi ref của case. Mỗi claim chỉ trích ref thuộc domain liên quan (`CLAIM_DOMAINS`; claim đòi hoàn tiền dùng policy, payment, refund, shipment). Không có ref phù hợp thì lấy 2 ref đầu.

**Luật `_detect`** (theo thứ tự): refund `failed` → `refund_failed`; refund `pending` → `refund_pending`; đơn `canceled`/`unavailable` đã bị trừ tiền → `canceled_order_paid`/`unavailable_order_paid`; hai capture cùng số tiền và tổng lớn hơn tiền đơn → `duplicate_charge`; có sự kiện `reconciliation_mismatch` → `payment_mismatch`; nhiều loại thanh toán → `valid_split_payment`; khách nhận sau ngày dự kiến → seller bàn giao sau hạn thì `late_delivery_seller`, không thì `late_delivery_logistics`.

Evidence không bao giờ dùng lại giữa các case: mỗi case một `_Investigation`, và mỗi call truyền đúng `case_id`.

## 5. Failure and efficiency policy

| Failure | Retry budget | Fallback | Trace event/code |
| --- | ---: | --- | --- |
| MCP timeout / lỗi tool | 0 | Tool đó coi như không có dữ liệu; case vẫn chạy với các tool còn lại. Nếu cả `get_order` và `get_customer_history` đều lỗi thì dừng cả lần chạy (`RuntimeError`), không xuất output thiếu bằng chứng | Không emit `tool_result_consumed` cho call lỗi; CLI thoát mã 1 |
| Entity not found/ambiguous | 0 | `not_found` hoặc `ambiguous`, confidence 0.3; candidate không có trong lịch sử bị reject | `entity_resolution.status` |
| Source conflict | 0 | Ưu tiên lịch sử khách, loại lần mua sau `opened_at`, chọn lần mua khớp topic | `data_conflicts` với `PURCHASE_IN_SCOPE_OF_CASE` |
| Invalid specialist result | 0 | Output không đúng schema làm CLI dừng trước khi ghi file; bất biến sai làm `solve_case` raise | Không có `case_finalized` cho case đó |

**Không retry** vì mọi call (kể cả call lỗi) đều bị audit và tính vào efficiency, và `get_refund_timeline` báo lỗi khi đơn không có refund (lỗi tất định, retry vô ích).

**Ngân sách call.** 6 call mỗi case, 600 call cho 100 case. So sánh v2 (620 call) và v4 (640 call) cho thấy ngân sách khoảng 6 call/case; v5 đưa mọi case về đúng 6 call và đạt efficiency 93.96 (trần). Cách giữ ngân sách:
- Chọn tool theo nhóm topic; không gọi shipment cho case thanh toán và ngược lại.
- Không gọi `get_refund_timeline` cho canceled/unavailable (v1 có 20/20 call lỗi).
- Không gọi `get_sellers` (seller có sẵn trong `get_order_items`); không gọi product cho refund_*.
- Không gọi MCP cho candidate placeholder.
- Mỗi tool gọi tối đa một lần mỗi case.

**Quota server.** Key bị từ chối sau khoảng 1.300 call trong một giờ (ước tính từ các lần bị chặn, chưa được ban tổ chức xác nhận). Tối đa hai lần chạy đầy đủ mỗi giờ; phát triển luật offline bằng snapshot.

## 6. Verification invariants

Kiểm tra trước khi finalize:

| Invariant | Cách đảm bảo |
| --- | --- |
| Schema | CLI validate output theo `l3b-output-v2.schema.json` trước khi ghi; `day09 validate` kiểm lại toàn bộ outputs và trace |
| Entity scope | `resolved_order_ids` và `rejected_candidates` rời nhau theo cách xây dựng; mọi MCP call dùng đúng `order_id` đã resolve |
| Rejected candidates | Mọi candidate không có trong lịch sử khách đều nằm trong `rejected_candidates` |
| Evidence ownership | Verifier assert mọi ref trong output thuộc `_Investigation` của case này |
| Claim linkage | Ref của từng claim là tập con của `evidence_refs` |
| Timeline | Lần mua sau `opened_at` bị loại; refund sau `opened_at` bị bỏ |
| Payment/refund totals | `refundable = max(captured − refunded, 0)`; `recommended_refund_brl` bằng tổng `refund_lines` |
| Source precedence | Lịch sử khách hơn `get_order`; mâu thuẫn ghi vào `data_conflicts` |
| Responsibility/action | `case_status`, action, số tiền lấy nguyên từ policy; seller mẫu của policy được thay bằng seller thật của đơn; `late_seller_ids` chỉ có khi `late_delivery_seller` |
| Status/refund | Verifier assert `no_action` thì số tiền hoàn bằng 0 |
| Confidence bounds | 0.95 khi kết luận là topic, 0.5 khi `insufficient_evidence`; claim 0.9–0.95; entity 0.3–0.95; mọi giá trị trong [0, 1] |

Kiểm tra offline bổ sung: `data/check_outputs.py` (luồng routing và các luật nhất quán). Trước khi nộp: không case nào có `evidence_refs` rỗng.

## 7. Reproducibility

- **Model/config:** không dùng LLM. Hằng số trong `workflow.py`: bảng chọn tool theo topic, `CLAIM_DOMAINS`, confidence 0.95/0.9/0.5. Policy `EC_POLICY_V2`.
- **Môi trường:** Python 3.12.10 (yêu cầu ≥ 3.11). Dependency đã cài: `mcp` 2.2.0, `httpx2` 2.13.1, `jsonschema` 4.26.0, `python-dotenv` 1.2.3 (ràng buộc trong `pyproject.toml`).
- **Concurrency:** tuần tự, một case một lúc, một phiên MCP cho cả lần chạy.
- **Random seed:** không có; toàn bộ tất định. Cùng dữ liệu MCP cho cùng output (trừ `evidence_ref` và thời gian trong trace, do server và đồng hồ sinh ra).
- **Lệnh chạy (PowerShell):**
  ```powershell
  .venv\Scripts\activate
  $env:PYTHONIOENCODING = "utf-8"
  day09 validate-inputs
  day09 run
  day09 validate
  day09 package --output dist/submission.zip
  ```
- **Chạy lại offline:** `python data/replay.py <case_id> ...` dùng snapshot trong `data/mcp_samples/`, không gọi MCP.
- **Tài nguyên:** khoảng 600 MCP call và 10–20 phút cho 100 case; quota khoảng 1.300 call mỗi giờ mỗi team.
- **Bí mật:** API key chỉ nằm trong `.env` (đã gitignore); không ghi vào output, trace hay tài liệu.
