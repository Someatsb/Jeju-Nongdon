# 게시판 고정본 (2026-11-14 받음)

시험과 재생(`notice.bat --replay S1`)이 인터넷에 나가지 않도록 받아 둔 공식 게시판 페이지를 줄여 둔 것이다.
받은 곳은 아래 네 게시판 목록 주소와 검색 두 번뿐이고(GET 만, 요청 사이 1초 이상, 요청에 이름·메일 등 아무 정보도 넣지 않음), 상세는 이미 받아 둔 공고 페이지를 같은 방식으로 줄였다.

- 목록(`*_list.html`, `*_search_fta.html`): 표의 앞뒤 틀은 그대로 두고 글 줄을 9~12개만 남겼다. 사람 이름이 든 줄과 휴대전화·메일이 든 줄은 없다.
- 상세(`detail_*.html`): 본문 틀(`board-view` 또는 `view-wrap`)만 남겼다. 제주시 글의 작성자 칸에 있던 직원 이름은 부서 이름으로 바꿨다.
- `index.json`: 주소 → 파일 이름. 시험의 가짜 받기(`notice_board.fixture_http`)가 이것만 본다.
- `data/replay/boards/` 는 이 폴더의 복사본이다(재생 모드가 쓴다). 시험이 같은지 확인한다.

| 파일 | 받은 주소 |
|---|---|
| `seogwipo_list.html` | https://www.seogwipo.go.kr/info/news/notice.htm |
| `seogwipo_search_fta.html` | https://www.seogwipo.go.kr/info/news/notice.htm?q=FTA&qType=title |
| `jejusi_list.html` | https://www.jejusi.go.kr/information/intro/news.do |
| `jejusi_search_fta.html` | https://www.jejusi.go.kr/information/intro/news.do?searchText=FTA&currentPageNo=1 |
| `jejusi_farm_list.html` | https://www.jejusi.go.kr/part/farm/intro/news.do |
| `jeju_farm_list.html` | https://www.jeju.go.kr/farm/notice/notice/notice1.htm (가장 최근 글이 2026-08-18) |
| `detail_jsi_farm_youth_loan.html` | https://www.jejusi.go.kr/part/farm/intro/news.do?mode=detail&notice_id=16a47b830c1a4522b0b9071ddf20bcc3 |
| 그 밖의 `detail_*` | 앞서 받아 둔 공고 페이지(서귀포시 알림마당 4건, 제주시 공지사항 1건) |

받은 주소 수: 목록 4 + 검색 2 + 상세 1 = 7번.
