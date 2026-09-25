# L3B Architecture Record

Tài liệu này mô tả chi tiết kiến trúc hệ thống Multi-Agent phục vụ giải quyết khiếu nại thương mại điện tử (K4 L3B — Multi-Agent MCP + A2A). Thiết kế tập trung vào tính khả kiểm (verifiable decisions), tuân thủ nguyên tắc Least Privilege, bảo vệ toàn vẹn bằng chứng (evidence provenance), xử lý xung đột dữ liệu (source conflicts) và tối ưu hóa hiệu quả sử dụng MCP Gateway.

---

## 1. System overview

Hệ thống được tổ chức theo mô hình **Hierarchical Multi-Agent Architecture kết hợp Directed Acyclic Graph (DAG)**. Quy trình điều tra một case khiếu nại tuân thủ nghiêm ngặt chu trình từ xác thực thực thể đến điều tra chuyên môn, xử lý xung đột và kiểm chứng độc lập.

### 1.1 Kiến trúc tổng thể và luồng dữ liệu

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                           INCOMING CASE                                                │
│                                  (inputs/<case_id>.json, case-set.json)                                │
└───────────────────────────────────────────────────┬────────────────────────────────────────────────────┘
                                                    │
                                                    ▼
                                            [ Coordinator ] ──────── (trace: case_received)
                                                    │
                                                    │ task_assigned
                                                    ▼
                                      [ Entity/Customer Agent ] ◄────► [ MCP: Customer & Order Domain ]
                                                    │                  (get_customer_history, lookup_order)
                                                    │ handoff (resolved_order_ids, customer_context)
                                                    ▼
                                            [ Coordinator ]
                                                    │
                        ┌───────────────────────────┼───────────────────────────┐
                        │ task_assigned             │ task_assigned             │ task_assigned
                        ▼                           ▼                           ▼
            [ Order/Product Agent ]         [ Shipment Agent ]         [ Payment/Refund Agent ]
                    ▲                               ▲                           ▲
                    │                               │                           │
                    ▼                               ▼                           ▼
          [ MCP: Order/Item/Prod ]        [ MCP: Shipment Domain ]    [ MCP: Payment/Refund Domain ]
          (order_details, items)          (shipment_details, timeline) (payment_details, refund_status)
                        │                           │                           │
                        └───────────────────────────┼───────────────────────────┘
                                                    │ handoff (domain findings & evidence_refs)
                                                    ▼
                                            [ Coordinator ]
                                                    │
                                                    │ task_assigned
                                                    ▼
                                        [ Policy/Conflict Agent ] ◄──► [ MCP: Policy Domain ]
                                                    │                  (get_policy_rules)
                                                    │ - Source Precedence Hierarchy
                                                    │ - Root Cause & Financial Resolution
                                                    │ handoff (draft resolution, data_conflicts)
                                                    ▼
                                            [ Coordinator ]
                                                    │
                                                    │ task_assigned
                                                    ▼
                                              [ Verifier ]
                                                    │
                                                    │ - Invariant Checks (Schema, Math, Provenance)
                                                    │ - Confidence Calibration
                                                    │ (trace: verification_completed)
                                                    ▼
                                            [ Coordinator ]
                                                    │
                                                    ├──► outputs/<case_id>.json
                                                    └──► traces/trace.jsonl (trace: case_finalized)
```

### 1.2 Các giai đoạn vòng đời của một Case (Case Lifecycle)

1. **Giai đoạn tiếp nhận (Ingestion & Dispatch)**: Coordinator nhận case, khởi tạo case context, cấp phát in-memory evidence cache cục bộ cho case và phát event `case_received`.
2. **Giai đoạn giải quyết thực thể (Entity Resolution)**: `entity_customer_agent` truy vấn MCP để đối soát thông tin khách hàng và lịch sử đơn, phân loại các candidate order IDs thành `resolved_order_ids` hoặc `rejected_candidates`.
3. **Giai đoạn điều tra chuyên biệt (Specialist Investigation)**:
   - Nếu không giải quyết được thực thể (`not_found`), chuyển thẳng sang xử lý thiếu bằng chứng để tiết kiệm quota MCP.
   - Nếu thực thể được xác định (`resolved`), Coordinator điều phối song song hoặc tuần tự các Specialist: `order_product_agent`, `shipment_agent`, `payment_refund_agent`.
4. **Giai đoạn dung hòa xung đột & định sách (Conflict Resolution & Policy)**: `policy_conflict_agent` phát hiện các mâu thuẫn giữa lời khai khách hàng và dữ liệu hệ thống/vận chuyển/thanh toán, áp dụng thứ bậc nguồn tin (Source Precedence Hierarchy) để chọn `selected_source`, xác định bên chịu trách nhiệm và lập phương án bồi hoàn tài chính.
5. **Giai đoạn kiểm chứng bất biến (Verification)**: `verifier` chạy bộ kiểm tra tất cả các điều kiện bất biến (schema, tài chính, logic trách nhiệm, tính hợp lệ của evidence refs).
6. **Giai đoạn hoàn tất (Finalization)**: Coordinator ghi output đã kiểm chứng vào `outputs/<case_id>.json` và phát event `case_finalized`.

---

## 2. Agent ownership

Áp dụng chặt chẽ nguyên tắc **Đặc quyền tối thiểu (Principle of Least Privilege)**: Việc MCP Gateway hỗ trợ Tool Discovery không đồng nghĩa với việc mọi agent đều được quyền gọi mọi tool. Quyền hạn gọi tool được phân định theo đúng phạm vi trách nhiệm (domain bounded context).

| Actor | Input | Trách nhiệm | Tool permission | Output / Handoff |
| :--- | :--- | :--- | :--- | :--- |
| **Coordinator** (`coordinator`) | Raw case JSON từ `inputs/<case_id>.json` | Điều phối workflow DAG, quản lý state và vòng đời case, điều phối handoff giữa các agents, tổng hợp draft payload trước khi chuyển cho Verifier. | **Không có quyền gọi MCP tools** (chỉ quản lý luồng điều phối và trace). | Handoff task tới các Specialist Agents và Verifier. |
| **Entity/Customer Agent** (`entity_customer_agent`) | Thông tin khách hàng, complaint text, danh sách candidate order IDs, transaction timestamps. | Đối soát các candidate orders với khiếu nại, tính toán matching score, quyết định `resolved`, `ambiguous` hoặc `not_found`; trích xuất `customer_unique_id` và `related_order_ids`. | Domain: `customer`, `order`<br>Tools: `get_customer_history`, `get_customer_orders`, `lookup_order` | Handoff về `coordinator` với `entity_resolution` và `customer_context`. |
| **Order/Product Agent** (`order_product_agent`) | Resolved `order_ids`, danh sách item/product được đề cập trong claim. | Trích xuất thông tin chi tiết đơn hàng (trạng thái: delivered, canceled, unavailable,...), danh mục mặt hàng (`item_ids`), định danh người bán (`seller_ids`), giá niêm yết và cước vận chuyển. | Domain: `order`, `item`, `product`, `seller`<br>Tools: `get_order_details`, `get_order_items`, `get_product_info` | Handoff về `coordinator` với `affected_entities` (items, sellers) và order status snapshot. |
| **Shipment Agent** (`shipment_agent`) | Resolved `order_ids`, `shipping_limit_date`, địa chỉ nhận hàng, carrier telemetry. | Phân tích toàn trình vận chuyển, so sánh mốc giao hàng thực tế với ước tính (estimated delivery), so sánh hạn giao hàng của seller (`shipping_limit_date`) với thời điểm xuất kho; xác định `verdict` (`on_time`, `seller_delay`, `logistics_delay`, `lost`, `returned`,...) và `late_seller_ids`. | Domain: `shipment`, `seller`<br>Tools: `get_shipment_details`, `get_tracking_timeline` | Handoff về `coordinator` với `shipment_analysis` và `shipment_ids`. |
| **Payment/Refund Agent** (`payment_refund_agent`) | Resolved `order_ids`, thông tin thanh toán, claim về tiền. | Đối soát giao dịch tài chính, phân tích thanh toán phân tách (split payments: voucher, credit card, boleto), phát hiện trừ tiền trùng (`duplicate_capture`), tính toán chính xác `captured_total_brl`, `refunded_total_brl`, và `refundable_total_brl`. | Domain: `payment`, `refund`<br>Tools: `get_payment_details`, `get_refund_status` | Handoff về `coordinator` với `payment_analysis` và `payment_references`. |
| **Policy/Conflict Agent** (`policy_conflict_agent`) | Kết quả tổng hợp từ các Specialist, nội dung khiếu nại, quy định sàn. | Phát hiện xung đột dữ liệu (`data_conflicts`), giải quyết xung đột theo thứ bậc nguồn tin; xác định `primary_issue`, xếp hạng nguyên nhân (`ranked_causes`), quy trách nhiệm (`responsible_parties`), tính toán bồi hoàn (`financial_resolution`) và đề xuất `resolution_actions`. | Domain: `policy`<br>Tools: `get_policy_rules` | Handoff về `coordinator` với toàn bộ đánh giá nghiệp vụ và chính sách. |
| **Verifier** (`verifier`) | Toàn bộ draft output payload được Coordinator tổng hợp. | Kiểm chứng tính bất biến trước khi phát hành output: kiểm tra JSON Schema (`l3b-output-v2`), đối soát số học tài chính, kiểm tra tính toàn vẹn và phạm vi bằng chứng (`evidence_refs`), bảo đảm tính nhất quán logic giữa các trường. | **Không có quyền gọi MCP tools** (chỉ phân tích dữ liệu nội bộ đã thu thập). | Ghi nhận trace event `verification_completed` kèm decision attributes (PASS / REJECT). |

---

## 3. Entity resolution và A2A protocol

### 3.1 Thuật toán Entity Resolution (Xếp hạng & Reject Candidates)

Một số case khiếu nại không cung cấp `order_id` chính xác mà chỉ cung cấp tập candidate orders hoặc thông tin định danh khách hàng mờ. Quy trình phân giải thực thể được thiết kế như sau:

1. **Trích xuất đặc trưng so khớp (Feature Extraction)**:
   - **Temporal Match ($w_t = 0.30$)**: Chênh lệch thời gian giữa mốc khiếu nại và thời gian tạo đơn (`order_purchase_timestamp`). Đơn hàng phát sinh trong khoảng 1–30 ngày trước khiếu nại có trọng số cao nhất.
   - **Financial Match ($w_f = 0.30$)**: Độ lệch giữa số tiền khách hàng khiếu nại và tổng giá trị đơn hàng (items + freight).
   - **Item & Category Semantic Match ($w_i = 0.25$)**: Mức độ tương đồng giữa từ khóa/mô tả sản phẩm trong khiếu nại với danh mục hoặc tiêu đề sản phẩm trong candidate order.
   - **Order Status Anomaly ($w_s = 0.15$)**: Các đơn có trạng thái bất thường (`canceled`, `unavailable`, giao chậm, khiếu nại trước đó) nhận điểm ưu tiên đối soát.
2. **Tính toán Composite Confidence Score ($S \in [0, 1]$)**:
   $$S = w_t \cdot S_{\text{temporal}} + w_f \cdot S_{\text{financial}} + w_i \cdot S_{\text{item}} + w_s \cdot S_{\text{status}}$$
3. **Ngưỡng phân loại (Decision Thresholds)**:
   - **$S_{\text{top}} \ge 0.75$ và $(S_{\text{top}} - S_{\text{second}}) \ge 0.20$**: Trạng thái **`resolved`**. Đưa candidate có điểm cao nhất vào `resolved_order_ids`. Tất cả các candidate còn lại đưa vào `rejected_candidates`.
   - **$0.40 \le S_{\text{top}} < 0.75$ hoặc chênh lệch $(S_{\text{top}} - S_{\text{second}}) < 0.20$**: Trạng thái **`ambiguous`**. Không thể xác định duy nhất đơn hàng bị ảnh hưởng.
   - **$S_{\text{top}} < 0.40$**: Trạng thái **`not_found`**. Toàn bộ candidate orders đều bị loại bỏ vào `rejected_candidates` kèm theo lý do cụ thể (ví dụ: `TIME_OUT_OF_RANGE`, `PRICE_MISMATCH`, `PRODUCT_UNRELATED`).

### 3.2 Giao thức A2A (Agent-to-Agent Protocol)

- **Message Envelope**: Giao tiếp nội bộ giữa các agent tuân thủ cấu trúc dữ liệu chuẩn hóa:
  ```python
  @dataclass(frozen=True)
  class AgentMessage:
      case_id: str             # Định danh case duy nhất dùng để correlation
      sender: str              # Tên actor gửi (ví dụ: "entity_customer_agent")
      recipient: str           # Tên actor nhận (ví dụ: "coordinator")
      task_type: str           # Loại nhiệm vụ (ví dụ: "INVESTIGATE_SHIPMENT")
      payload: dict[str, Any]  # Dữ liệu nghiệp vụ có cấu trúc
      evidence_refs: list[str] # Danh sách bằng chứng liên quan đã thu thập
      timestamp: str           # ISO-8601 UTC
  ```
- **Correlation theo `case_id`**: Mọi tin nhắn nội bộ, request MCP và trace event đều bắt buộc mang `case_id`. Bất kỳ thông điệp nào không khớp `case_id` hiện hành đều bị hủy ngay lập tức.
- **Điều kiện Handoff (Handoff Contract)**:
  - *Pre-condition*: Agent gửi đã hoàn thành việc gọi các tool cần thiết, trích xuất dữ liệu, validate schema cục bộ và liên kết toàn bộ `evidence_refs`.
  - *Action*: Coordinator ghi nhận trace event `handoff` với `actor=sender`, `target=recipient`.
  - *Post-condition*: Agent nhận xác nhận đã nhận dữ liệu; nếu payload rỗng hoặc thiếu trường bắt buộc, Coordinator kích hoạt fallback policy.
- **Chống vòng lặp (Loop Prevention) & Timeout**:
  - Luồng A2A là **Strict Directed Acyclic Graph (DAG)**: Không có cơ chế phản hồi tạo chu trình (ví dụ: Verifier không handoff ngược lại Specialist mà chỉ báo lỗi cho Coordinator).
  - Giới hạn số bước điều phối tối đa cho một case là 8 bước (`MAX_HOPS = 8`).
  - Timeout cho từng sub-agent là 10.0 giây; timeout toàn bộ case là 30.0 giây.
- **Trace Hygiene**:
  - Tuyệt đối **không** đưa prompt, chain-of-thought, dữ liệu suy luận cá nhân hay API key vào trace.
  - Trace chỉ ghi các sự kiện vòng đời quan sát được theo đúng schema `day09-trace-event-v1`: `case_received`, `task_assigned`, `tool_result_consumed`, `handoff`, `policy_decided`, `verification_completed`, `case_finalized`.

---

## 4. Evidence và conflict lifecycle

### 4.1 Vòng đời Bằng chứng (Evidence Lifecycle)

Mọi dữ liệu từ bên ngoài dùng để ra quyết định đều phải bắt nguồn từ MCP Gateway và được audit minh bạch.

1. **Validation & Ingestion**:
   - Khi Gateway trả kết quả, hệ thống validate ngay lập tức với schema `mcp-evidence-response-v1.schema.json`.
   - Kiểm tra định dạng bắt buộc: `evidence_ref` (regex `^ev_[A-Za-z0-9_-]{20,96}$`), `result_hash` (`^sha256:[a-f0-9]{64}$`), `domain`, và `data`.
2. **In-Memory Per-Case Caching**:
   - Khởi tạo bộ nhớ đệm cache dạng dict có key là `(case_id, tool_name, json_hash(arguments))`.
   - Nếu một tool được gọi với cùng đối số trong cùng một case, kết quả được trả về từ cache thay vì gọi lại Gateway (bảo toàn quota efficiency).
3. **Cách ly tuyệt đối giữa các Case (Zero Cross-Scope Leakage)**:
   - Khi chuyển sang case mới, toàn bộ evidence cache được dọn sạch (`cache.clear()`).
   - `evidence_refs` chỉ có hiệu lực nội bộ trong case đã sinh ra nó. Tuyệt đối không lưu trữ hay tái sử dụng bằng chứng qua các case khác nhau (tránh vi phạm hard gate `cross_scope_evidence_ref`).
4. **Ghi nhận sử dụng bằng chứng (`tool_result_consumed`)**:
   - Ngay khi một agent sử dụng thông tin từ `evidence["data"]` để đưa ra nhận định hoặc trích xuất thuộc tính, TraceWriter phải emit event `tool_result_consumed`:
     - `actor`: Tên agent đang tiêu thụ bằng chứng.
     - `tool_name`: Tên MCP tool đã cung cấp dữ liệu.
     - `evidence_refs`: Mảng chứa `evidence_ref` tương ứng.

### 4.2 Xử lý xung đột nguồn tin (Source Conflict Lifecycle)

Trong thương mại điện tử, thông tin thường xuyên xảy ra mâu thuẫn giữa lời khai của người mua, xác nhận của người bán và số liệu ghi nhận từ hệ thống vận chuyển/thanh toán.

#### Phân cấp ưu tiên nguồn dữ liệu (Source Precedence Hierarchy)

Khi phát hiện cùng một trường dữ liệu (`field`) có giá trị khác nhau giữa các nguồn, hệ thống áp dụng thứ bậc ưu tiên cố định:

```text
┌────────────────────────────────────────────────────────────────────────┐
│  Tier 1: Telemetry & Gateway Logs (Độ ưu tiên cao nhất)                 │
│  - Carrier Logistics Telemetry (Mốc quét mã vạch bưu cục, chữ ký nhận) │
│  - Payment Gateway Transaction Records (Bank auth code, capture log)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Overrules
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Tier 2: Platform Core Records & Seller Operational Logs               │
│  - Platform Order Database (Mốc tạo đơn, thời điểm hủy đơn chính thức) │
│  - Seller Dispatch Logs (Biên bản bàn giao hàng cho đơn vị vận chuyển) │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Overrules
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Tier 3: Subjective Assertions (Độ ưu tiên thấp nhất)                  │
│  - Customer dispute claims (Lời khai chủ quan của khách hàng)          │
│  - Unverified seller statements (Tuyên bố miệng của người bán)         │
└────────────────────────────────────────────────────────────────────────┘
```

#### Quy tắc xử lý và Biểu diễn trong Output (`data_conflicts`)

- **Xung đột thời gian giao hàng**: Khách hàng khiếu nại "Chưa nhận được hàng" nhưng Carrier Tracking API ghi nhận trạng thái `delivered` kèm timestamp và chữ ký $\rightarrow$ `selected_source = "carrier_tracking"`, `resolution_code = "CARRIER_TELEMETRY_OVERRULES_CUSTOMER_CLAIM"`.
- **Xung đột trạng thái thanh toán**: Khách hàng khiếu nại bị trừ tiền 2 lần, Payment Gateway ghi nhận 1 giao dịch thành công và 1 giao dịch bị từ chối (`failed`) $\rightarrow$ `selected_source = "payment_gateway"`, `resolution_code = "GATEWAY_CONFIRMS_SINGLE_CAPTURE"`.
- **Xung đột không thể dung hòa (Unresolved Contradictions)**: Nếu hai nguồn cùng Tier cung cấp dữ liệu trái ngược nhau mà không có nguồn đối chứng $\rightarrow$ Đặt `selected_source = null`, `resolution_code = "UNRESOLVED_CONTRADICTION_ESCALATED"`, và thiết lập `case_status = "needs_investigation"`.

---

## 5. Failure and efficiency policy

### 5.1 Ma trận xử lý lỗi (Failure Recovery Matrix)

| Tình huống lỗi | Ngân sách Retry | Chiến lược Fallback | Trace Event & Action |
| :--- | :---: | :--- | :--- |
| **MCP Timeout / HTTP 5xx** | Tối đa 1 lần retry (backoff 1.0s) | Bỏ qua tool, đánh dấu domain tương ứng là `insufficient_evidence`. Tiếp tục quy trình với các bằng chứng đã có. | `actor="coordinator"`, `event_type="policy_decided"`, `decision_code="MCP_TIMEOUT_FALLBACK"` |
| **Entity Not Found / Ambiguous** | 0 retry (không đoán mò) | Thiết lập `entity_resolution.status = "not_found"` hoặc `"ambiguous"`, bỏ qua các bước gọi tool vận chuyển/thanh toán để tiết kiệm quota; gán `case_status = "needs_investigation"` hoặc `primary_issue = "insufficient_evidence"`. | `actor="entity_customer_agent"`, `event_type="policy_decided"`, `decision_code="ENTITY_RESOLUTION_FAILED"` |
| **Source Conflict không thể dung hòa** | 0 retry | Ghi nhận conflict vào `data_conflicts` với `selected_source = null`. Không ép buộc kết luận sai sự thật; hạ `confidence` xuống $\le 0.50$. | `actor="policy_conflict_agent"`, `event_type="policy_decided"`, `decision_code="CONFLICT_UNRESOLVED"` |
| **Specialist Output không hợp lệ** | Tối đa 1 lần retry (format correction) | Dùng template fallback tối thiểu với các giá trị trung lập (`insufficient_evidence`, `reconciled = false`), không để sập workflow. | `actor="coordinator"`, `event_type="policy_decided"`, `decision_code="SPECIALIST_FALLBACK_INVOKED"` |
| **MCP Gateway Rate Limit (429)** | Tối đa 2 lần retry (exponential backoff 2.0s, 4.0s) | Giảm tốc độ gọi tool, chuyển sang thực thi tuần tự cho case hiện tại. | `actor="coordinator"`, `event_type="policy_decided"`, `decision_code="RATE_LIMIT_BACKOFF"` |

### 5.2 Chính sách tối ưu hóa cuộc gọi MCP (Efficiency Policy)

Tiêu chí `efficiency` chiếm 5% điểm số tổng thể và được tính dựa trên per-case call budget. Việc gọi thừa thãi hoặc quét diện rộng sẽ làm suy giảm điểm số nghiêm trọng.

1. **Ngân sách cuộc gọi mục tiêu (Target Call Budget)**:
   - Giới hạn tối đa **từ 4 đến 8 MCP calls** cho mỗi case thông thường.
   - Không vượt quá 10 calls trong bất kỳ trường hợp phức tạp nào.
2. **Cơ chế Lazy Fetching (Truy vấn theo nhu cầu thực tế)**:
   - Chỉ gọi MCP tools thuộc domain `shipment` khi khiếu nại liên quan đến giao trễ, thất lạc hoặc hư hỏng hàng.
   - Chỉ gọi MCP tools thuộc domain `payment`/`refund` khi khiếu nại liên quan đến số tiền, hủy đơn hoặc bồi hoàn.
   - Tuyệt đối không gọi toàn bộ danh mục tool của Gateway cho mọi case (No broad scan).
3. **Idempotency & Zero Hallucination**:
   - Tất cả các thao tác trích xuất từ dữ liệu tool đều mang tính tất định (idempotent).
   - Khi thiếu bằng chứng, hệ thống bắt buộc kết luận `insufficient_evidence` thay vì tự suy đoán dữ liệu nhằm đảm bảo tính toàn vẹn nghiệp vụ.

---

## 6. Verification invariants

Trước khi một case được ghi vào `outputs/<case_id>.json`, agent `verifier` phải chạy độc lập một bộ quy tắc kiểm tra bất biến (Verification Invariants). Nếu có bất kỳ vi phạm nào, output phải được hiệu chỉnh hoặc gắn cờ trước khi xuất xưởng.

```text
                               Draft Case Payload
                                       │
                                       ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                           VERIFIER INVARIANTS                           │
  │                                                                         │
  │  [Invariant 1] Full Schema Compliance (day09-l3b-output-v2)             │
  │  [Invariant 2] Entity Disjointness (resolved ∩ rejected = ∅)            │
  │  [Invariant 3] Provenance Integrity (all refs audited, current case)    │
  │  [Invariant 4] Shipment Verdict & Late Seller Alignment                 │
  │  [Invariant 5] Financial Reconciliation & Refund Conservation           │
  │  [Invariant 6] Business Issue & Action Consistency                      │
  │  [Invariant 7] Claim Linkage Completeness                               │
  │  [Invariant 8] Confidence Calibration Bounds                            │
  └────────────────────────────────────┬────────────────────────────────────┘
                                       │
                       ┌───────────────┴───────────────┐
                       │                               │
                  [All Passed]                  [Rule Violated]
                       │                               │
                       ▼                               ▼
             Emit Trace Event:               Deterministic Correction
         verification_completed              or Downgrade Confidence
                       │                               │
                       ▼                               ▼
                 Final Output                   Corrected Output
```

### Chi tiết các quy tắc bất biến (Invariants)

1. **Schema Compliance Invariant**:
   - Output phải tuân thủ 100% JSON Schema `day09-l3b-output-v2.schema.json`.
   - `additionalProperties: false` trên toàn bộ các object; bắt buộc có đầy đủ 13 trường cấp cao nhất.
2. **Entity Consistency Invariant**:
   - Tính tách biệt tuyệt đối giữa candidate được chọn và bị loại:
     $$\text{resolved\_order\_ids} \cap \text{rejected\_candidates} = \emptyset$$
   - Tập `affected_entities.order_ids` phải là tập con của `resolved_order_ids`.
3. **Evidence Provenance & Scope Invariant**:
   - Tất cả mã trong `evidence_refs` (ở cấp root và trong từng `claim_assessments`) phải tuân thủ định dạng `^ev_[A-Za-z0-9_-]{20,96}$`.
   - Mọi `evidence_ref` xuất hiện trong output phải nằm trong danh sách các bằng chứng mà hệ thống đã thực sự nhận được từ MCP Gateway trong phiên chạy của đúng `case_id` đó.
   - Nghiêm cấm đưa ref của case khác hoặc ref tự sinh vào output (Hard Gate Prevention).
4. **Shipment Consistency Invariant**:
   - Nếu `shipment_analysis.verdict == "seller_delay"`, thì danh sách `late_seller_ids` không được rỗng và các seller này phải thuộc `affected_entities.seller_ids`.
   - Nếu `timeline_complete == false`, hệ thống không được đưa ra kết luận khẳng định lỗi hoàn toàn do vận chuyển trừ khi có bằng chứng tracking xác thực.
5. **Financial Arithmetic & Conservation Invariant**:
   - Luôn thỏa mãn: `captured_total_brl >= refunded_total_brl` (trừ khi có bằng chứng lỗi hệ thống ngân hàng ghi nhận rõ).
   - `refundable_total_brl` phải thỏa mãn công thức:
     $$\text{refundable\_total\_brl} = \max(0.0, \text{round}(\text{captured\_total\_brl} - \text{refunded\_total\_brl}, 2))$$
   - `recommended_refund_brl` phải bằng chính xác tổng `amount_brl` của tất cả các dòng trong `refund_lines`:
     $$\text{recommended\_refund\_brl} = \sum \text{line.amount\_brl}$$
   - Số tiền đề xuất hoàn không được vượt quá số tiền còn có thể hoàn: $\text{recommended\_refund\_brl} \le \text{refundable\_total\_brl}$.
6. **Business Issue & Action Alignment Invariant**:
   - Nếu `primary_issue == "unsupported_claim"`, thì `case_status` phải là `"no_action"`, `recommended_refund_brl == 0`, và `resolution_actions` không được chứa hành động bồi hoàn tiền.
   - Nếu `primary_issue` thuộc nhóm lỗi do người bán (`late_delivery_seller`, `canceled_order_paid`), thì `root_cause_analysis.responsible_parties` phải có ít nhất một bên mang `party_type = "seller"`.
   - Nếu `primary_issue == "late_delivery_logistics"`, `responsible_parties` phải chứa `logistics_provider`.
7. **Claim Linkage Invariant**:
   - Mỗi claim trong `claim_assessments` phải chứa ít nhất một `evidence_ref` hợp lệ minh chứng cho kết luận (`verdict`) của claim đó.
8. **Confidence Calibration Invariant**:
   - `confidence` của `assessment` và `entity_resolution` phải nằm trong đoạn $[0.0, 1.0]$.
   - Khi `primary_issue == "insufficient_evidence"` hoặc `entity_resolution.status != "resolved"`, giá trị `confidence` không được vượt quá **0.65**.
   - Tránh việc đặt `confidence = 1.0` tuyệt đối; các trường hợp đầy đủ bằng chứng đồng thuận được gán điểm hiệu chuẩn trong khoảng $[0.85, 0.95]$.

---

## 7. Reproducibility

### 7.1 Môi trường thực thi & Ràng buộc phụ thuộc

Hệ thống được thiết kế để chạy tái lập 100% trên môi trường tiêu chuẩn Python 3.11+.

- **Python Runtime**: `Python >= 3.11`
- **Thư viện cốt lõi (Pinning dependencies theo `pyproject.toml`)**:
  - `httpx2 >= 2, < 3`: Client HTTP bất đồng bộ giao tiếp MCP với timeout cấu hình chuẩn (connect=30s, read=300s).
  - `mcp >= 2, < 3`: Bộ SDK MCP chuẩn hỗ trợ streamable HTTP transport và ClientSession.
  - `jsonschema[format] >= 4.25, < 5`: Công cụ kiểm tra hợp đồng Draft 2020-12 với bộ format checker (date-time).
  - `python-dotenv >= 1.1, < 2`: Quản lý biến môi trường an toàn.

### 7.2 Tính tất định (Determinism) & Cấu hình suy luận

- **Cấu hình mô hình (nếu sử dụng LLM Reasoning Engine)**:
  - `temperature = 0.0`: Loại bỏ tính ngẫu nhiên của mô hình tạo sinh.
  - `top_p = 1.0`, `seed = 42`: Đảm bảo cùng input sẽ cho ra cùng kết quả output.
  - Sử dụng JSON Schema Guided Decoding / Structured Outputs để loại bỏ lỗi cú pháp.
- **Quy tắc tất định (Deterministic Heuristics Engine)**:
  - Khâu đối soát số học tài chính, trích xuất ID thực thể và phân cấp ưu tiên nguồn tin được xử lý bằng mã nguồn Python thuần túy (pure deterministic functions), đảm bảo tính toán luôn chính xác tuyệt đối.

### 7.3 Giới hạn tài nguyên & Kiểm soát tương tranh

- **Giới hạn tương tranh (Concurrency Control)**:
  - Khi xử lý tập 100 cases, hệ thống sử dụng `asyncio.Semaphore(3)` (tối đa 3 cases được xử lý đồng thời).
  - Mục đích: Tránh gây nghẽn hàng đợi hoặc kích hoạt cơ chế Rate Limit (429) từ MCP Gateway.
- **Giới hạn tài nguyên (Resource Constraints)**:
  - Bộ nhớ RAM tiêu thụ: `< 512 MB`.
  - Thời gian xử lý: Trung bình `< 5.0s / case`, timeout tối đa `25.0s / case`.

### 7.4 Hướng dẫn thực thi & Đóng gói bài nộp

```bash
# 1. Kích hoạt môi trường và cài đặt package
python -m pip install -e ".[dev]"

# 2. Kiểm tra bộ test hợp đồng ban đầu
pytest -q

# 3. Xác thực tính toàn vẹn của tập case đầu vào (sau khi giải nén)
day09 validate-inputs

# 4. Kiểm tra kết nối và liệt kê MCP tools được phát hiện
day09 mcp-tools

# 5. Thực thi toàn bộ workflow điều tra 100 cases
day09 run

# 6. Xác thực tính hợp lệ của toàn bộ output và trace file
day09 validate

# 7. Đóng gói file nộp bài chuẩn quy cách
day09 package --output dist/submission.zip
```

> [!IMPORTANT]
> **Bảo mật**: Tuyệt đối không lưu trữ `COMPETITION_TEAM_API_KEY`, credentials cá nhân hoặc thông tin nhạy cảm vào mã nguồn, output JSON hay trace log. Submission ZIP (`dist/submission.zip`) chỉ chứa `manifest.json`, `trace.jsonl` và `outputs/<case_id>.json`.
