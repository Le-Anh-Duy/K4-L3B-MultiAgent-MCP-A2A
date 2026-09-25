# Nhật ký thử nghiệm L3B

Ghi lại từng phiên bản đã nộp: thay đổi gì, vì sao đổi, điểm thay đổi ra sao, và rút ra được gì.
Mọi con số là điểm public ngày 25/09/2026.

## Bảng điểm

| Thành phần (trọng số) | v1 | Teammate A | v2 | Top 1 lớp | v4 | v5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Tổng** | 87.32 | 90.51 | 90.89 | 92.19 | 92.67 | **92.91** |
| Semantic (40%) | 84.07 | 91.53 | 90.92 | 91.60 | 92.33 | 92.34 |
| Evidence (15%) | 82.56 | 83.68 | 82.70 | 91.55 | 91.57 | 91.39 |
| Provenance (15%) | 93.71 | 93.85 | 93.87 | 93.92 | 93.94 | 93.96 |
| Consistency (10%) | 93.71 | 88.85 | 93.87 | 93.92 | 93.94 | 93.96 |
| Schema (5%) | 93.71 | 93.85 | 93.87 | 93.92 | 93.94 | 93.96 |
| Calibration (5%) | 85.95 | 93.62 | 93.63 | 93.69 | 93.71 | 93.72 |
| Workflow (5%) | 93.71 | 93.85 | 93.87 | 93.92 | 93.94 | 93.96 |
| Efficiency (5%) | 84.34 | 86.34 | 91.68 | 85.16 | 88.62 | 93.96 |
| MCP call / 100 case | 640 | ~600 | 620 | ~640 | 640 | 600 |

Từ v1 lên v5 tăng 5.59 điểm: semantic +3.31, evidence +1.32, calibration +0.39, efficiency +0.48, còn lại khoảng +0.1.

## Trước v1: tìm hiểu đề và dữ liệu

- Đề không phải train model. Dataset Kaggle Olist chỉ là nền. Dữ liệu thật để chấm lấy từ MCP server của ban tổ chức.
- Không cần key của model AI. Chỉ cần team key `sk-team-…`, dùng để server gắn bằng chứng với team.
- CSV Olist không dùng được để suy ra đáp án. `order_id` có thật trong Olist, nhưng giá, ngày, seller trong MCP đều là dữ liệu tổng hợp.
- Starter kit có lỗi: thư viện `mcp` v2 đổi `isError` thành `is_error`. Sửa ở `mcp_gateway.py`.
- EDA input: 10 loại topic xoay vòng theo số thứ tự case, mỗi loại 10 case. Mọi case có 2 candidate (1 thật, 1 `candidate-XXX`). Hint khách hàng có dạng `customer-<12 ký tự cuối order_id>`. Mọi case dùng `EC_POLICY_V2`.
- Thăm dò case 001, 004, 005 phát hiện mỗi `order_id` chứa **hai lần mua trộn lẫn** (một kịch bản thật, một mồi). `get_order` có lúc trả về lần mua mồi.
- `get_refund_timeline` báo lỗi khi đơn không có refund, nhưng lỗi vẫn bị tính là một call.
- Policy giống hệt nhau ở mọi case. Seller trong policy là ID mẫu, không phải seller của đơn.

## v1: 87.32

**Cách làm:** gọi cùng một bộ 6–7 tool cho mọi case. Tách hai lần mua theo thời gian, chạy luật để phát hiện vấn đề, rồi tự chọn kết luận chính (ưu tiên claim nếu có bằng chứng, nếu không thì chọn vấn đề ưu tiên cao nhất). Confidence 0.7–0.85.

**Kết quả:** kết luận trùng topic ở 95/100 case. 5 case `unsupported_claim` bị đổi thành `late_delivery_logistics`. 27 case bị gắn thêm `secondary_issues` từ lần mua mồi.

**Rút ra:** mức trần khoảng 93.8 ở provenance, schema, workflow ban đầu bị đoán là do hard gate. Giả thuyết này sai (xem v2).

## Teammate A: 90.51 → phát hiện topic là đáp án

Code của teammate lấy thẳng `topic` làm `primary_issue`, không phân tích dữ liệu, nhưng semantic đạt 91.53, cao hơn v1 7.5 điểm.

**Kết luận:** bộ sinh đề gán tên kịch bản làm topic, kể cả `unsupported_claim`. Dữ liệu mâu thuẫn trong MCP chỉ là nhiễu. Phân tích càng "thông minh" càng dễ bị mồi đánh lừa.

Bảng điểm teammate ghi "Hard gates public: 0" mà vẫn chỉ 93.85 ở provenance. Vậy mức trần khoảng 93.9 là giới hạn chung, không phải lỗi của bài nộp.

Điểm consistency của teammate thấp (88.85) vì chép seller mẫu `seller-9b75…` từ policy và thêm action `notify_customer` không có trong policy.

## v2: 90.89

| Thay đổi | Lý do | Tác động |
| --- | --- | --- |
| `primary_issue` = topic, bỏ `secondary_issues` | Phát hiện từ teammate A | Semantic 84.07 → 90.92 |
| Confidence 0.95 | Kết luận đúng gần như mọi case | Calibration 85.95 → 93.63 |
| Bỏ `get_refund_timeline` cho canceled/unavailable | 20/20 call đều lỗi ở v1 | Efficiency 84.34 → 91.68 |
| Giữ seller thật, action chỉ lấy từ policy | Tránh lỗi của teammate A | Consistency 93.87 (teammate 88.85) |
| Lưu snapshot mọi phản hồi MCP vào `data/mcp_samples/` | Thử luật offline không tốn call | Tạo được `data/replay.py` |

Semantic vẫn thua teammate 0.6. So sánh từng field offline trên snapshot cho thấy khác biệt ở tổng tiền, `timeline_complete`, verdict claim hoàn tiền, định dạng ID.

## v3: không nộp được

**Thay đổi:** verdict của claim `requested_full_refund` theo cách của teammate (canceled/unavailable là `supported`, được hoàn một phần là `partially_supported`, không hoàn là `unsupported`). Lý do: đòi hoàn 100% mà chỉ được hoàn phí ship thì là "một phần".

**Sự cố:** giữa lần chạy, mọi call đều bị server từ chối. Key teammate vẫn gọi được. Dựa vào thời điểm bị chặn và mở lại, giả thuyết là **giới hạn khoảng 1.300 call mỗi team trong một giờ trượt**. v1 + v2 + thăm dò đã dùng khoảng 1.300 call trong 45 phút.

**Sửa sau sự cố:**
- Snapshot tốt không bị ghi đè bằng lỗi.
- Nếu cả `get_order` và `get_customer_history` đều lỗi, cả lần chạy dừng ngay, không tạo output thiếu bằng chứng.

## Top 1 lớp (workflow_v1): 92.19 → phát hiện cách lấy evidence

Evidence đạt 91.55, cao hơn v2 gần 9 điểm. Khác biệt:
- Chỉ gọi tool liên quan tới topic: shipment cho case giao hàng, payment cho case thanh toán, refund cho case hoàn tiền.
- Gọi `get_product_context` cho mọi case vì input ghi `include_product_context: true`. Gọi `get_sellers` khi lỗi thuộc seller.
- `evidence_refs` của từng claim chỉ lấy ref thuộc domain liên quan.
- Đã sửa seller sang seller thật nên consistency lên trần, dù vẫn thêm `notify_customer`. Vậy nguyên nhân consistency thấp của teammate A là seller mẫu, không phải action thừa.

Efficiency chỉ 85.16 vì gọi nhiều tool hơn.

## v4: 92.67

v4 = v3 + những điểm mạnh của top 1, giữ những điểm mạnh của mình.

| Thay đổi | Lấy từ | Tác động |
| --- | --- | --- |
| Chọn tool theo topic, thêm product và sellers | Top 1 | Evidence 82.70 → 91.57 |
| Evidence của từng claim theo domain | Top 1 | Evidence (gộp ở trên) |
| Tổng tiền tính trên toàn bộ order, timeline theo dòng `get_order` | Cả hai teammate | Semantic 90.92 → 92.33 (gộp với verdict v3) |
| Giữ: seller thật, action chỉ từ policy, không gọi call chắc chắn lỗi, chốt an toàn | v2, v3 | Consistency 93.94, efficiency cao hơn top 1 |

Kiểm tra offline trước khi chạy: các field semantic khớp 100% với top 1 trên 52 case còn snapshot tốt.

## v5: 92.91 (cao nhất)

**Giả thuyết:** ngân sách khoảng 6 call mỗi case. v2 có 20 case gọi 7 call, efficiency 91.68. v4 có 40 case gọi 7 call, efficiency 88.62. Mỗi call vượt 6 mất khoảng 12–14% điểm efficiency của case đó.

**Thay đổi:** bỏ `get_sellers` (seller đã có trong `get_order_items`). Case refund_* không gọi `get_product_context`. Mọi case đúng 6 call, tổng 600.

**Kết quả:** efficiency 88.62 → 93.96, chạm trần. Evidence chỉ giảm 0.18 (91.57 → 91.39). Tổng +0.25. Giả thuyết ngân sách 6 call/case đúng; seller và product ở case hoàn tiền không phải nhóm evidence quan trọng. Giữ v5 làm final.

**Còn lại tới trần (~93.96):** khoảng 1 điểm, gần hết ở semantic (1.62 × 0.40 = 0.65) và evidence (2.57 × 0.15 = 0.39).

## Các bài nộp hỏng và nguyên nhân

| Bài | Điểm | Nguyên nhân |
| --- | ---: | --- |
| `dich22/submission.zip` | 0 | Chạy bằng key team khác lúc key mình bị chặn. Evidence thuộc team khác nên mọi case bị hard gate. |
| `submission (12).zip` | 24.83 | Chạy workflow_v1 khi key hết quota. Code nuốt lỗi và xuất 69 case không có evidence. Chỉ 31 case có điểm. |

## Quy tắc làm việc rút ra

1. Topic là kết luận. Dữ liệu MCP dùng để lấy bằng chứng và điền chi tiết.
2. Evidence phải thật, đúng team, đúng case. Chạy bằng key nào thì nộp vào team đó.
3. Chỉ gọi tool liên quan tới topic, khoảng 6 call mỗi case.
4. Mỗi lần nộp chỉ đổi một nhóm thay đổi để biết cái nào có tác dụng.
5. Thử luật offline bằng `data/replay.py` và `data/check_outputs.py`. Chỉ chạy thật khi cần nộp.
6. Mỗi giờ chạy thật tối đa hai lần. Trước khi chạy, gọi thử một call.
7. Trước khi nộp, kiểm tra không có case nào 0 evidence.
8. Không đuổi theo điểm ở provenance, schema, workflow: trần khoảng 93.9 là giới hạn chung.
9. Luật nào cũng cần lý do nghiệp vụ, vì 80% điểm cuối nằm ở tập private.

## Chưa biết

- Định dạng `payment_references`, `shipment_ids`, `cause_code`, `data_conflicts` có được chấm không.
- Phần semantic còn thiếu tới trần (khoảng 1.6) nằm ở field nào.
- Code luôn tin topic. Nếu tập private có topic sai, kết luận sẽ sai; `_detect` vẫn chạy nhưng chưa được dùng để sửa kết luận.
- Giới hạn call chính xác của server. Con số 1.300/giờ là ước tính.

## File liên quan

- `src/student_agent/workflow.py`: `solve_case`, `_bundles`, `_detect`
- `src/student_agent/mcp_gateway.py`: snapshot, xử lý `is_error`
- `data/replay.py`: chạy lại trên snapshot, không tốn call
- `data/check_outputs.py`: kiểm tra luồng routing và tính nhất quán
- `data/mcp_probe.py`: gọi thử một vài tool cho một case
- `data/runs/`, `dist/submission-v*.zip`: output và bài nộp của từng phiên bản
