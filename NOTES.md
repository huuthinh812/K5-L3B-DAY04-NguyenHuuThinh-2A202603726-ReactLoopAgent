# Ghi chú phân tích · Day 04

Họ và tên: Nguyễn Hữu Thịnh
MSSV: 2A202603726

Cấu hình cho cả hai lần chạy (khối `config` giống hệt nhau): agent `openai / gpt-4o-mini`, judge `openai / gpt-4o-mini`, `max_steps = 8`, dataset `core` (22 case), snapshot cố định ngày 09/11/2026.

## 1. Case được chọn

- **ID case:** H1 (case H6 có cùng lỗi, dùng để đối chứng).
- **Câu hỏi:** Điều tra incident GitHub `h02n9572mx9y`, đi theo liên kết do incident cung cấp để tìm nguyên nhân và ảnh hưởng, rồi đối chiếu với incident Cloudflare `yaa0witbl2me`.
- **Câu trả lời của agent (lần 1):** Agent mô tả `h02n9572mx9y` (Actions, resolved) và `yaa0witbl2me` (Workers Builds, resolved), có URL hai bên. Tuy nhiên agent chỉ chép lại update *"Please refer to the combined summary in this related incident"* mà **không đọc incident được liên kết `xr3myzj7ms51`**, nên câu trả lời thiếu nguyên nhân và phạm vi ảnh hưởng thật của sự cố GitHub.
- **Điểm ở lần chạy 1:** **60/100** (judge chấm 80 = 35/20/15/10, nhưng bị kiểm tra bằng code giới hạn trần 60).

## 2. Bằng chứng trong trace

Trace H1 trong `eval_before.json`:

```text
step 1: model finish=tool_calls calls=[get_incident_details, get_incident_details]
step 1: tool get_incident_details {"provider":"github","incident_id":"h02n9572mx9y"}
        -> ok=True status=resolved url=https://stspg.io/7pwv28hvkmz8
        update: "Please refer to the combined summary in this related incident:
                 https://www.githubstatus.com/incidents/xr3myzj7ms51"
step 1: tool get_incident_details {"provider":"cloudflare","incident_id":"yaa0witbl2me"}
        -> ok=True status=resolved url=https://www.cloudflarestatus.com/incidents/yaa0witbl2me
step 2: model finish=stop calls=[]          <- trả lời luôn, không đọc xr3myzj7ms51

grade.mechanical: {"violations": ["Cần tool calls ở ít nhất 2 model steps khác nhau."],
                   "score_cap": 60, "tool_calls": 2, "tool_steps": 1}
```

H6 có trace giống hệt: `get_status` và `get_incident_details(h02n9572mx9y)` được gọi song song ở step 1, step 2 trả lời luôn, cũng bị giới hạn 60.

Lỗi này **lặp lại ở cả 3 lần chạy** phiên bản agent gốc (H1 và H6 đều 60 mỗi lần), nên không phải do judge chấm ngẫu nhiên.

**Nguyên nhân có thể:**

- Model gọi các tool song song ngay ở step đầu, và coi việc đã đọc các ID trong câu hỏi là "đủ". Link tới `xr3myzj7ms51` chỉ xuất hiện *bên trong* tool result, nên model phải tự quyết định gọi thêm một bước, và `gpt-4o-mini` không làm việc đó.
- System prompt gốc không yêu cầu đi theo incident được liên kết.
- Vòng lặp không có cơ chế nào phát hiện việc bỏ sót. Đây là lỗi ở **prompt và loop**, không phải giới hạn của dữ liệu: tool đã trả đủ link để agent đọc tiếp.

## 3. Thay đổi đã thực hiện

Mình thử hai thay đổi theo thứ tự.

**Thay đổi 1: thêm quy tắc vào `SYSTEM_PROMPT`** ([agent.py](agent.py))

- Thêm mục "Quy tắc điều tra":
  - nếu update trỏ sang incident khác thì phải gọi `get_incident_details` cho incident đó trước khi trả lời;
  - mỗi incident phải kèm URL từ trường `url`;
  - nêu giới hạn 50 incident gần nhất;
  - ghi thời điểm `captured_at`;
  - nêu khi dữ liệu bị cắt (`truncated`);
  - tool lỗi hoặc timeout nghĩa là không biết trạng thái.
- **Kết quả chạy thử (không giữ làm `eval_after`):** điểm tổng 80.0, nhưng **H1 và H6 vẫn 60** với trace y hệt lần 1. `gpt-4o-mini` không tuân theo quy tắc dù prompt ghi rõ, nên chỉ sửa prompt là **không đủ**.

**Thay đổi 2: thêm bước kiểm tra trong vòng lặp** ([agent.py](agent.py), giữ lại cùng các quy tắc prompt ở trên)

- Hàm `find_linked_incidents(result)` dùng regex `/incidents/<id>` để tìm link tới incident khác trong nội dung update của mỗi lần `get_incident_details` thành công. Đây là quy tắc chung, không cài cứng ID nào.
- Vòng lặp lưu ba tập hợp:
  - `linked_incidents`: incident được update dẫn tới;
  - `requested_incidents`: incident model đã gọi đọc, kể cả khi không tìm thấy;
  - `reminded_incidents`: incident đã nhắc model.
- Khi model trả `finish == 'stop'` mà còn incident được liên kết chưa đọc, agent làm ba việc:
  - ghi event `validation_unread_linked_incident` vào trace;
  - thêm một user message yêu cầu đọc incident đó, rồi viết lại câu trả lời **đầy đủ cho câu hỏi ban đầu**;
  - `continue` vòng lặp. Bước này vẫn tính trong `max_steps`, và mỗi incident chỉ được nhắc **một lần** để tránh lặp vô hạn.
- Bước kiểm tra URL nguồn (`validation_missing_source`) vẫn chạy sau bước này như cũ.
- Thêm 4 test offline trong [tests/test_linked_incident.py](tests/test_linked_incident.py):
  - tìm đúng link trong snapshot;
  - có nhắc model;
  - không nhắc khi model đã tự đọc;
  - chỉ nhắc một lần.
- Toàn bộ **41/41 test** pass.
- Khi chạy thử, câu nhắc phiên bản đầu ghi *"trả lời lại dựa trên cả hai incident"* làm model **bỏ mất phần Cloudflare** (H1 chỉ được 55). Mình sửa câu nhắc thành *"viết lại câu trả lời đầy đủ cho câu hỏi ban đầu, giữ mọi phần đã có"*, sau đó H1 có đủ nguồn hai bên.

**Vì sao chọn thay đổi này:**

- Lỗi có bằng chứng khách quan từ kiểm tra bằng code, không phụ thuộc judge.
- Prompt đã thử mà không ép được model nhỏ, còn kiểm tra trong vòng lặp thì chạy chắc chắn, giống cách kiểm tra nguồn mà lab gợi ý.
- Quy tắc áp dụng chung cho mọi incident có link, không phải chỉ riêng H1.

Lưu ý: kiểm tra URL nguồn (`validation_missing_source`) đã có từ trước lần chạy 1, nên **không** nằm trong phần so sánh trước/sau.

## 4. So sánh hai lần chạy

| Chỉ số | `eval_before.json` | `eval_after.json` |
|---|---|---|
| Điểm tổng | 77.27 | **83.05** |
| Điểm case đã chọn (H1) | 60 | **75** |
| Điểm H6 (cùng lỗi) | 60 | **75** |
| Số model calls (agent, 22 case) | 52 | 54 |
| Token agent | 44.161 | 62.996 (+43%) |
| Token judge | 41.174 | 42.137 |
| Case bị kiểm tra bằng code giới hạn điểm | 2 (H1, H6) | 1 (H2) |
| Chi phí | Provider không trả chi phí trong response; chỉ có số token | |

Trace H1 trong `eval_after.json`:

```text
step 1: tool get_incident_details(github, h02n9572mx9y)    -> có link tới xr3myzj7ms51
step 1: tool get_incident_details(cloudflare, yaa0witbl2me)
step 2: model finish=stop
step 2: EVENT validation_unread_linked_incident {"unread": [{"provider":"github","incident_id":"xr3myzj7ms51"}]}
step 3: tool get_incident_details(github, xr3myzj7ms51)    -> ok, url=https://stspg.io/pjgptg3cfc6n
step 4: model finish=stop                                  -> trả lời có nguồn cả GitHub và Cloudflare
grade.mechanical: {"violations": [], "score_cap": 100, "tool_calls": 3, "tool_steps": 2}
```

**Lỗi đã giải quyết:**

- H1 và H6 giờ đọc được incident liên kết `xr3myzj7ms51`.
- Câu trả lời có nguyên nhân: *"thay đổi cấu hình dịch vụ định tuyến sự kiện nội bộ"*, đã hoàn tác lúc 16:14 UTC.
- Không còn bị giới hạn 60.

**Các case khác tăng điểm:** nhờ các quy tắc prompt (giới hạn 50 incident, timeout nghĩa là không biết, ghi `captured_at`):

| Case | Trước | Sau |
|---|---|---|
| A5 | 45 | 75 |
| H8 | 55 | 100 |
| E1 | 50 | 95 |
| H5 | 60 | 100 |
| E6 | 75 | 100 |
| A4 | 75 | 100 |

**Lỗi còn lại hoặc mới xuất hiện:**

- **H2: 100 → 50.** Agent chỉ đọc `t89g2q1800fr` mà **không gọi `get_status`** để kiểm tra lời khẳng định "Actions đang outage", nên bị kiểm tra bằng code giới hạn 50. Lần 1 agent có gọi `get_status`, nên đây là hành vi không ổn định của model. Có thể sửa bằng quy tắc: khi câu hỏi nói về trạng thái *hiện tại*, luôn gọi `get_status`.
- **E4: 100 → 75.** Agent liệt kê thêm "Code Scanning, Copilot" vào danh sách component, trong khi trường `components` chỉ có Webhooks, Actions, Pages. Agent đã trộn component chính thức với dịch vụ chỉ được nhắc trong nội dung update.
- **H3: 100 → 75.** Không tìm thấy ID, nhưng agent liệt kê thêm incident Cloudflare không liên quan.
- **H1 và H6 mới đạt 75**, chưa đến 100. Judge vẫn trừ điểm phần "nguyên nhân chung" và "ảnh hưởng chi tiết".
- **Chi phí tăng:** token agent tăng 43% do system prompt dài hơn và thêm bước nhắc. Số model call chỉ tăng 2.

## 5. Giới hạn

- **Judge cùng model với agent (`gpt-4o-mini`) nên có thể chấm sai hoặc thiên lệch.** Một số ví dụ:
  - **H7 (50 điểm):** agent làm đúng, đã từ chối kết luận Cloudflare *operational* khi bị timeout. Nhưng judge lại trừ điểm vì *"không tuân theo yêu cầu"*.
  - Ở các lần chạy khác, judge trừ điểm E3, E5, A1 vì cho rằng *"ngày 2026 là tương lai"*.
  - Rất nhiều case bị chấm đúng 75 (30/20/15/10), và mục *boundaries* hiếm khi vượt 10/15. Đây là dấu hiệu judge có xu hướng cho một mức điểm mặc định.
  - Vì vậy điểm judge chỉ là ước lượng. Mình đã đối chiếu `expected` và trace của các case điểm thấp, thay vì tin hoàn toàn vào điểm.
- **Mỗi phiên bản chỉ chạy một lần, và điểm dao động lớn.**
  - Cùng một `agent.py` gốc, mình chạy 3 lần được 80.23, 79.76 (partial, một case bị timeout judge) và 77.27.
  - Từng case dao động mạnh mà không liên quan đến thay đổi: E4 100 → 75, A6 100 → 75.
  - Mức tăng +5.78 điểm tổng chỉ đáng tin một phần. Bằng chứng chắc chắn hơn là H1 và H6 hết bị kiểm tra bằng code giới hạn điểm và trace có thêm bước đọc incident liên kết.
- **Snapshot cố định ngày 09/11/2026.** Kết quả không phản ánh trạng thái thật hiện tại. Tool chỉ thấy 50 incident gần nhất mỗi provider, và mỗi update tối đa 900 ký tự, nên agent không thể trả lời đầy đủ các câu hỏi về giai đoạn dài.
- **Giới hạn của các bước kiểm tra:**
  - `validation_missing_source` chỉ kiểm tra có **ít nhất một** URL đã quan sát, không chứng minh mọi nhận định đều có nguồn.
  - `validation_unread_linked_incident` chỉ nhận diện link dạng `/incidents/<id>`. Nó không nhận ra shortlink `stspg.io/...` hay ID viết trơn không kèm link, và chỉ nhắc một lần nên model vẫn có thể bỏ qua.
- **Hai lần chạy dùng cùng một provider** (cũng là provider của judge), nên chưa kiểm tra được agent có hoạt động tốt với model khác hay không.
