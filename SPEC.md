# SPEC.md — 랜덤 좌표 생존기 시스템 명세

> 코드 기준 명세. 규칙·수치의 원본은 코드(`survival/config.py`, `survival/state.py`)이고, 이 문서는 구조와 책임을 요약한다.
> 플레이어용 설명은 `README.md`에 있다.

## 1. 개요
- **장르:** LLM 게임 마스터(GM)가 서술하는 한국어 텍스트 생존 게임
- **목표:** 지구의 랜덤 육지 좌표에서 시작해 서울 반경 `ARRIVAL_RADIUS_KM`(60km) 안으로 들어오면 승리. 체력이 0이 되면 패배
- **기술 스택:** Python 3.11, Gradio(UI), OpenAI Responses API 또는 Google Gemini(OpenAI 호환 Chat Completions) + Function Calling(GM), Images API 또는 Gemini 그림 모델 + Vision(장면 그림), scikit-learn(위험도 모델), 임베딩 RAG(ChromaDB, 없으면 numpy), Open-Meteo / Nominatim(날씨·기후·지명)
- **실행:** `.venv/bin/python app.py` (`.env`에 `OPENAI_API_KEY` 또는 `GEMINI_API_KEY` 필요)
- **테스트:** `.venv/bin/pytest -q` (네트워크·API 없이 검증. 현재 247개)

## 2. 설계 원칙: "숫자는 엔진, 이야기는 LLM"
- GM은 체력·돈·위치·소지품을 **직접 바꾸지 못한다.** 툴 호출로 엔진에 요청만 하고, 엔진(`GameState`)이 규칙 검사와 변화 폭 제한을 한다.
- GM이 툴을 빠뜨리거나 서술이 엔진 상태와 어긋나는 경우를 막는 **사후 보정 단계**가 있다(5장).
- 판정을 GM보다 **엔진이 먼저** 할 수 있는 것(기회 수락·되풀이, 범죄 의도)은 GM 호출 전에 판정해 결과만 GM에게 전달한다.

## 3. 모듈별 책임

| 모듈 | 책임 |
|---|---|
| `app.py` | Gradio 화면 구성, 새 게임/이어하기, 턴 실행(`play`), 장면 그림 갱신 여부 판단 |
| `survival/state.py` | `GameState` 데이터클래스(모든 필드)와 공통 규칙: 시간 흐름, 생체 수치, 날씨·기후, 장면·인물, 단서와 사실, 턴 시작/종료, `create_game`. 아래 믹스인 5개를 상속한다 |
| `survival/inventory.py` | `InventoryMixin`: 소지품 넣고 빼기, 먹고 마시기(용량·일부만 마시기), 돈 쓰기. 소지품 판정 함수(`item_core`, `consumable_effect` 등) |
| `survival/crime.py` | `CrimeMixin`: 자유 행동 판정, 범죄 기록·목격·수배도, 원한을 가진 사람, 체포 |
| `survival/travel.py` | `TravelMixin`: 이동 수단(`travel`), 요금·표, 탈것(훔치기·사기 `buy_vehicle`·주유 `refuel`)과 운전, 국경 검문(`_border_check`), 새 장소 도착(`arrival_place`) (13장) |
| `survival/journey.py` | `JourneyMixin`: 목적지로 가기(`go_to`), 여러 턴 여정, 공관·공항, 귀국 지원 |
| `survival/offers.py` | `OfferMixin`: 기회의 조건·계획·수락·거절·만료와 반복 방지 |
| `survival/police.py` | `PoliceMixin`: 수배 단계(★1~5), 경찰 등장(`roll_police`), 대응 판정(`respond_to_police`), 은신(`lay_low`), 변장. 입력 → 대응 종류(`classify_response`) (11장) |
| `survival/economy.py` | `EconomyMixin`: 일(`work`, 시급·기술), 팔기(`sell_item`, 시세), 방(`rent_room`, 은신처), 도박(`gamble`) (12장) |
| `survival/achievements.py` | 여정 기록(`record_turn`, `end_turn`에서 턴 기록으로 통계를 모음), 업적 16개, 명예의 전당(`saves/hall_of_fame.json`), 결산(`run_summary`) (14장) |
| `survival/util.py` | `clamp` 등 여러 모듈이 함께 쓰는 작은 도구 |
| `survival/gamemaster.py` | GM 지시문(`INSTRUCTIONS`), 입력 구성(`build_input`), 턴 루프(`run_turn`), 서술 사후 보정(한국어·장면·몸 상태·되풀이), 자동 소비·결제·수입 |
| `survival/llm.py` | LLM 공급자 연결. OpenAI는 클라이언트를 그대로 쓰고, Gemini는 Responses API·Images API 모양을 흉내 내는 어댑터(`GeminiClient`)로 감싼다 (9장) |
| `survival/tools.py` | GM이 호출하는 툴 스키마(`TOOLS`)와 실행(`execute_tool`), 툴 남용·요청하지 않은 행동 차단 가드, 기회 수락/되풀이 판정(`offer_action`) |
| `survival/events.py` | 바이옴 판별, 돌발 이벤트 178개, 대형 이벤트(기회) 9종, 수락/거절 어휘 |
| `survival/leads.py` | 단서(lead) 생성과 정체 공개: 단서가 생길 때 정체·방향·거리를 미리 확정 |
| `survival/intent.py` | 플레이어 입력의 범죄 의도 판정(키워드 + 조사 처리) |
| `survival/geo.py` | 랜덤 육지 좌표, 역지오코딩, 거리·방위 계산 |
| `survival/places.py` | 실제 도시 248곳(공관·국제공항 여부 포함), 가까운 도시 찾기 |
| `survival/weather.py` / `climate.py` | 실제 현재 날씨·16일 시간별 예보 / 최근 1년 기록 기반 기후대(8종)·계절 |
| `survival/risk_model.py` | RandomForest 위험도 예측(안전/주의/위험). 합성 데이터로 첫 실행 시 학습, `models/`에 저장 |
| `survival/knowledge.py` | 생존 지식 RAG(`data/survival_guide.txt`) |
| `survival/imagegen.py` | 장면 그림 생성·편집 지시문, Vision으로 그림 읽기, 새로 생긴 구조물 검사 |
| `survival/languages.py` | 나라별 표지판 언어(151개국) |
| `survival/flags.py` | `turn_flags`·`flags` 키 목록(TypedDict)과 뜻 |
| `survival/sound.py` | 게임 상태 → 배경 소리 층별 크기(0~1), 이번 턴의 사건 효과음 선택. 화면과 분리된 순수 함수 (10장) |
| `survival/static/sound.js` | 브라우저 소리 엔진. Web Audio로 합성하고, 상태창의 소리 신호가 바뀌면 층별 크기를 바꿈 |
| `survival/ui.py` | CSS, HUD(상태창) HTML, 알림 상자, 턴 요약 |
| `survival/savegame.py` | `saves/autosave.json` 자동 저장·불러오기 |
| `survival/config.py` | 모든 설정값과 밸런스 수치 |
| `mcp_server.py` | 엔진 기능 일부(좌표, 날씨, 위험도, 지식 검색)를 FastMCP 서버로 공개 |

## 4. 핵심 데이터: `GameState` (`survival/state.py`)
- **위치:** `lat`, `lon`, `place_name(_en)`, `country_code`, `place_type`(야생/마을/도시), `biome`, `distance`(서울까지 km)
- **생체 수치(0~100, `clamp`):** `health`, `satiety`, `hydration`, `energy`
- **자원:** `money`(USD), `items`, `tickets`, `vehicle`
- **시간:** `elapsed_hours`, `start_hour`, `utc_offset`(현재 위치 현지 시각), `turn`
- **환경:** `weather`, `forecast`, `climate`, `risk`
- **이야기 정합성:** `leads`(단서), `facts`(확정 사실), `characters`, `scene_*`(현재 장면), `journey`(여러 턴 이동)
- **기회:** `offer`(진행 중), `expired_offers`, `done_offers`(받아들이거나 거절해 끝난 기회. 재등장·되풀이 차단용)
- **범죄:** `wanted`(0~100, ★단계는 `police.heat_stage`), `crime_scene`, `enemies`, `notorious`, `stolen_items`
- **경제:** `skills`(일의 기술 Lv), `work_hours`, `lodging`(빌린 방 {lat, lon, place, until})
- **경찰:** `pursuit`(마주친 경찰 {stage, turn, who, kind: check/chase}), `disguise`({until, how})
- **턴 임시값:** `turn_flags`(`TurnFlags`), `delta`, `notices`, `event`. 장소의 사정은 `flags`(`PlaceFlags`). 두 dict의 키 목록과 뜻은 `survival/flags.py`에 있고, 새 키는 거기 먼저 적는다(`tests/test_flags.py`가 코드의 모든 키를 AST로 모아 대조)
- **상태 머신:** `status` = `playing` → `won`(서울 60km 이내) | `dead`(체력 0, `death_reason`)
- **분리 계획(`refactor/state-split`):** 기회 필드·메서드(`offer`, `*_offers`, `accept_offer` 등) → 기회 모듈, 여정(`journey`, `go_to`, `_advance_journey` 등) → 여정 모듈, 범죄(`wanted`, `crime_scene`, `enemies`, `notorious`, `stolen_items`, `attempt`, `arrest` 등) → 범죄 모듈. `GameState`는 데이터와 턴 경계(`begin_turn`/`end_turn`)만 남긴다. 저장 파일(`savegame`) 호환을 위해 필드 이름은 유지한다

## 5. 한 턴의 흐름 (`gamemaster.run_turn`)
1. `state.begin_turn()`: 스냅샷, 위험도 갱신, 돌발 이벤트 굴림, 대형 이벤트(기회) 굴림(방금 놓쳤거나 끝낸 기회, 범죄자로 알려진 곳의 도움 제안은 제외)
2. 입력 사전 판정: 범죄 의도(`crime_intent`), 기회 수락·되풀이(`resolve_offer_action` → `offer_action`)
3. GM 호출(Responses API, `previous_response_id`로 멀티턴). 대화를 잃으면 `make_recap`으로 새 대화를 시작
4. 툴 루프(최대 `MAX_TOOL_ROUNDS`=5): `execute_tool` → 결과 전달 → 재호출
5. 엔진 사후 보정: `guard_unrequested_move`, `auto_decline`, `auto_consume`, `auto_eat`, `settle_consumption`, `auto_charge`, `auto_money`
   - **서술 속의 돈(`money_mentions`):** 서술을 문장 단위로 읽어 금액마다 방향을 정한다. 금액 뒤 가장 가까운 동사로 받음·냄·잃음·훔침을 가리고, 뒤에 '겠·기로·수 있'이 붙으면 약속으로 무시한다. '건네(주)'는 앞에 받는 쪽 표시(당신에게·수고비·일당·보수·여비 등)가 있으면 받음, 다른 사람'에게'면 냄, 둘 다 없으면 모름. `auto_charge`는 냄, `auto_money`는 잃음·받음(범죄 의도가 없으면 훔침 제외)을 엔진이 돈을 움직이지 않았을 때만 반영한다
   - **`auto_eat`(GM이 먹고 마시기를 처리하지 않았을 때):** 입력에 나온 소지품을 먹은 것으로 처리한다. 이름이 여럿 걸리면 더 구체적인(긴) 이름을 고르고, 입력이 개울·강·샘·우물·빗물 같은 바깥의 물을 가리키면 가진 물을 대신 쓰지 않는다(그 물이 소지품에 있으면 그것을 쓴다)
   - **돈 알림(`money_notices`):** GM 툴(`pay`, `update_status`)로 움직인 돈은 `turn_flags.money_log`에 이유와 함께 남고, 그 금액이 서술에 없으면 "💸 지출 -$50 — 이유" / "💵 수입" 알림을 띄운다
6. `state.end_turn()`: GM이 시간을 흘리지 않았으면 입력으로 추정(`estimate_time`), 지난 기회 만료(제안은 나온 다음 턴까지만 유효), 사망·귀환 판정
7. 서술 보정: `ensure_korean` → `ensure_scene` → `ensure_vitals` → `enforce_redo`
8. 추천 행동 3개 확정(기회가 살아 있으면 1번은 '받아들이기')
9. `app.play`: 알림 + 서술 + 턴 요약 표시, 자동 저장, 필요하면 장면 그림 생성/편집

## 6. GM 툴 (`survival/tools.py`)
`advance_time`, `update_status`, `update_inventory`, `travel`, `attempt_action`, `add_lead`, `follow_lead`, `remember`, `go_to`, `seek_help`, `add_character`, `pay`, `acquire_vehicle`, `arrest`, `buy_ticket`, `accept_offer`, `decline_offer`, `set_scene`, `reject_event`, `search_survival_guide`

주요 가드: 플레이어가 말하지 않은 이동·차량 획득 차단, 한 턴 시간 중복 차단, 끝난 기회 되풀이 시 지급 차단(`redo_problem`), 출처 없는 이득 차단(`gain_problem`), 돈 증가 상한 `MONEY_GAIN_LIMIT`.

## 7. 주요 규칙 수치 (`survival/config.py`)
- 시작: 물 1L, 에너지바 2개, 라이터, 다용도 칼, 여권, 스마트폰(배터리 30%), $50
- 먹고 마시기: `CONSUMABLES` 표의 기본 회복량을 엔진이 보장(`settle_consumption`). 용량이 적힌 마실 것은 용량에 비례(`HYDRATION_PER_LITER`=45/L). "조금·한 모금·아껴·반만" 마시면 `sip_item`이 용량만 줄인다(`SIP_ML`=250ml, 반은 절반). 일부만 마신 턴에는 GM이 준 수분을 마신 양만큼으로, 용량이 적힌 물을 다 마신 턴에는 기본 회복량의 `MEASURED_DRINK_SLACK`(1.2)배로 깎는다(강물·음식처럼 용량을 모르는 것이 섞이면 GM을 따른다)
- 판정 성공률(`PLAY_STYLE`): cinematic(기본) easy 0.90 / normal 0.70 / hard 0.45 / very_hard 0.25, realistic 0.85 / 0.60 / 0.35 / 0.15. cinematic이면 성공의 15%가 극적인 성공(`CRITICAL_CHANCE`: 목격돼도 수배도 없음, 걸어 둔 돈 1.5배), 폭력적 실패의 30%가 가까스로 모면(`CLOSE_CALL_CHANCE`: 피해 절반). GM 지시문에 `CINEMATIC_NOTE`(영화적 연출 지침)가 붙는다
- 초반 `EARLY_GAME_HOURS`=12시간(36에서 완화) 동안은 마을까지만 이동(최대 60km). 공항은 공관 방문 또는 `AIRPORT_OPEN_DAY`=3일차부터(5에서 완화)
- 이동은 두 가지다. 수단·거리를 정한 이동(`travel` 툴)은 `TRAVEL_RULES`의 최대 거리 안에서 한 턴에 끝난다. 목적지를 말한 이동(`go_to` 툴, `journey`)은 한 턴에 최대 `JOURNEY_MAX_HOURS`=10시간씩 가고, 남으면 다음 턴에 이어간다
- 대형 이벤트 확률 0.10, 8턴 동안 없으면 확정 발생
- 수배도 50 이상이면 공항·항구에서 붙잡힐 수 있음

## 8. 테스트
- 주제별 테스트 파일: `test_state.py`(시간·수치·툴·턴·알림), `test_world.py`(거리·날씨·기후·지형·이벤트 조건·위험도·지식 검색·도시), `test_inventory.py`, `test_travel.py`, `test_journey.py`(목적지·단서·요청하지 않은 이동 차단), `test_crime.py`, `test_offers.py`, `test_narration.py`(GM 서술 보정), `test_scene.py`(장면·그림), `test_save.py`. 날씨·지명은 가짜로, GM 응답은 가짜 클라이언트(`SimpleNamespace`)로 대체해 네트워크 없이 실행한다.
- 공용: `tests/conftest.py`의 `game` 픽스처(몽골 온대림, 1일차 12시, 맑음, 초반 제한 없음)와 네트워크 차단, `tests/helpers.py`의 `fake_weather`·`call`(툴 실행)·`reply_with`(가짜 GM 응답)·`desert_noon`·`fix_roll`·`patch_everywhere`
- `tests/test_structure.py`: `GameState`가 믹스인으로 이루어졌는지, 메서드 이름이 겹치지 않는지, 나누기 전 메서드가 모두 있는지, 믹스인이 `state`를 가져오지 않는지(순환 import).
- **네트워크 차단(`tests/conftest.py`):** 모든 테스트에서 외부 접속을 막고, 막힌 시도가 한 번이라도 있으면 실패시킨다(날씨 조회처럼 오류를 삼키는 코드도 잡는다). 이름을 가져다 쓰는 함수를 가짜로 바꿀 때는 `tests/helpers.patch_everywhere`로 모든 `survival` 모듈을 함께 바꾼다
- `tests/test_flags.py`: 코드에서 쓰는 `turn_flags`/`flags` 키가 `flags.py`에 모두 적혀 있고 적힌 키가 쓰이는지(오탈자 방지).
- `tests/test_llm.py`: LLM 공급자 어댑터. `tests/test_sound.py`: 배경 소리·효과음(node가 있으면 `tests/js/sound_harness.js`로 sound.js를 가짜 브라우저에서 실행).
- **CI:** `.github/workflows/tests.yml`이 PR과 main 푸시마다 Python 3.11 + Node 20에서 `node --check`와 `pytest`를 돌린다. API 키·비밀 값은 쓰지 않는다. 키·캐시(`models/` 등)가 없는 깨끗한 체크아웃에서도 통과한다(위험도 모델은 처음에 자동 학습)

## 9. LLM 공급자 (`survival/llm.py`, `survival/config.py`)
- **고르기:** `.env`의 `LLM_PROVIDER`(openai/gemini). 없으면 키가 있는 쪽, 둘 다 있으면 OpenAI (`config.choose_provider`)
- **기본 모델:** OpenAI `gpt-4o-mini` + `text-embedding-3-small` + `gpt-image-1-mini`, Gemini `gemini-3.5-flash` + `gemini-embedding-001` + `gemini-3.1-flash-image`. `LLM_MODEL`, `EMBEDDING_MODEL`, `IMAGE_MODEL`로 바꿀 수 있다
- **Gemini 어댑터(`ChatResponses`):** 게임 코드는 Responses API 모양 그대로 호출한다. 어댑터가 이것을 Chat Completions로 바꾼다
  - 툴 정의: 평평한 Responses 형식 → `{"type": "function", "function": {...}}`
  - 입력: 문자열 → user 메시지, `function_call_output` → tool 메시지, `input_image` → `image_url`
  - 대화 이어가기: 응답 id별로 대화 기록을 메모리에 보관(최대 512개 응답, `threading.Lock`으로 공유 모드 동시 접속 보호, 대화당 60개 메시지. 자를 때는 user 메시지에서 끊어 툴 호출과 결과가 갈라지지 않게 함). 모델이 준 assistant 메시지는 `thought_signature`(extra_content)까지 그대로 돌려준다
  - 기록이 없는 `previous_response_id`(프로그램 재시작 후 이어하기)는 `LookupError` → `run_turn`이 줄거리(`make_recap`)로 새 대화를 시작
  - 출력 한도: Gemini는 생각 토큰도 한도에 포함하므로 `max_output_tokens`에 1024를 더한다(`GEMINI_REASONING_EFFORT`, 기본 low)
- **장면 그림(`GeminiImages`):** `client.images.generate/edit`를 `google-genai`의 `generate_content(response_modalities=["IMAGE"])`로 바꾼다. 편집은 이전 그림을 함께 보낸다. `size` → 화면비(1536x1024 → 3:2), 결과는 OpenAI와 같은 `data[0].b64_json`. 그림이 오지 않으면(차단 등) RuntimeError → `imagegen`이 이전 그림을 유지
- **그림 형식:** Gemini는 JPEG, OpenAI는 PNG를 준다. `imagegen._save`는 실제 형식(`llm.image_mime`)에 맞는 확장자로 저장하고, `read_image`도 그 형식으로 Vision에 보낸다
- `google-genai`가 설치되어 있지 않으면 글은 그대로 되고 그림만 실패한다
- **RAG 임베딩 캐시:** 임베딩 모델별로 따로 둔다(`models/guide_embeddings_<모델>.json`, ChromaDB 컬렉션 `survival_guide_<모델>`)

## 10. 배경 소리 (`survival/sound.py`, `survival/static/sound.js`)
- **원칙:** 무엇이 얼마나 크게 들려야 하는지는 엔진이 정하고(`soundscape(state)`), 브라우저는 그것을 합성만 한다. 그림과 같은 상태를 써서 그림·서술·소리가 맞는다
- **층(0~1):** `wind`(지형 기본값 + 실제 풍속, 눈보라·폭풍 가산), `rain`(실제 강수량 비례), `thunder`(폭풍), `birds`(낮, 지형별, 비 오면 줄어듦), `insects`(밤, 지형별, 8°C 미만·눈·폭풍이면 없음, 정글은 낮에도 약하게), `stream`/`waves`/`fire`(장면 이름·GM이 밝힌 것·그림에서 읽은 것에 개울·바다·모닥불이 있을 때), `crowd`/`traffic`(마을·도시·도로·공항, 밤에는 줄어듦)
- **실내:** 바깥 층은 0.3배(비는 0.5배), 불 소리는 그대로. 브라우저에서는 저역 통과 필터로 먹먹하게 한다
- **전달:** `app.view`가 상태창 HTML에 `<div id="rs-sound-cue" hidden data-cue="JSON">`을 붙인다. `sound.js`(`launch(head=...)`로 주입)가 MutationObserver로 값 변화를 감지해 2초에 걸쳐 크기를 바꾼다. 신호의 `key`가 같으면 무시한다
- **브라우저 정책:** 첫 클릭·키 입력 전에는 AudioContext를 만들지 않는다. 켜기/끄기와 크기는 `localStorage`(`rs-sound`)에 저장하고, 막혀 있어도 동작한다
- 게임이 끝나면(사망·귀환) 모든 층이 0
- **사건 효과음(`turn_sfx`):** 중요 알림과 같은 기록(`turn_flags`, `event`, `offer`, `status`)에서 고른다. 우선순위: 귀환·사망(단독) > 체포 > 기회 결과·판정 성공/실패 > 단서 정체(위험/발견) > 위험 이벤트 > 새 기회 > 새 단서 > 행운 > 탈것 > 표 > 이동 > 거절·만료·되풀이. 한 턴에 최대 3개
- **한 번만 울리기:** 신호의 `sfx = {events, nonce}`. nonce(턴·경과 시간·좌표·상태)가 바뀔 때만 울리므로, 같은 턴의 화면 갱신(진행 중 표시, 그림 갱신)에는 다시 울리지 않는다. 페이지를 연 직후 처음 받은 신호는 울리지 않고, 이어하기 화면은 `view(quiet=True)`로 빈 목록을 보낸다(저장된 마지막 턴의 소리를 다시 울리지 않게)
- **합성:** `sound.js`의 `SFX` 표(음표·노이즈 스윕·북소리). 효과음은 실내 필터를 거치지 않는 별도 경로(`sfxBus`)로 나간다. 소리를 꺼 두면 울리지 않는다
- **다른 탭:** `visibilitychange`로 숨겨지면 AudioContext를 멈추고, 돌아오면(소리가 켜져 있으면) 다시 켠다. 숨겨진 동안 온 효과음은 울리지 않는다

## 11. 경찰과 추격 (`survival/police.py`)
- **흐름(기회와 같은 방식):** `begin_turn`이 경찰 등장을 굴린다(`roll_police`, 이미 마주친 경찰이 있으면 굴리지 않음). 등장한 턴에는 GM이 "경찰이 다가오는 장면"까지만 서술하고(GM의 `arrest`는 막힘), **다음 턴의 플레이어 입력을 GM 호출 전에 엔진이 판정**한다(`gamemaster.resolve_police` → `respond_to_police`). GM은 `[경찰 대응 결과]`를 받아 서술만 하고, 그 턴에는 `attempt_action`·`arrest`가 막힌다
- **등장 확률:** ★2/3/4/5 기본 10/20/35/50% × 장소(도시 1.0, 마을 0.6, 야생 도로 0.4, 야생 0.15) × 밤 0.7 × 변장 0.4, 훔친 차 +15%p(최대 90%). ★4 이상이거나 훔친 차면 추격(chase), 아니면 검문(check)
- **대응 판정:** 입력의 말로 종류를 가린다(자수 > 뇌물 > 싸움 > 숨기 > 도주 > 둘러대기, 없으면 무시). 기본 확률 도주 .55 / 숨기 .50 / 뇌물 .70 / 둘러대기 .45 / 싸움 .35에서 ★마다 -6%, 보정(어둠 +10, 탈것 +15, 붐비는 도시 +5, 야생에서 숨기 +15, 변장 둘러대기 +25, ★4 이상 둘러대기 -25, 지침·부상 -15). 뇌물은 ★별 $20/40/80/150/300이 없으면 0%
- **결과:** 따돌림 수배도 -5(극적이면 -15), 뇌물 성공 -25(실패 +10), 싸움 성공 +20·체력 -10(실패 체력 -20), 자수 `_arrest(fine_rate=0.25, wanted_cut=60, hours=12)`, 무시 75% 체포. 실패는 `_arrest`(벌금 50%, 24시간, 수배도 -40, 탈것·표·훔친 물건 압수)
- **구금:** 12시간마다 포만감·수분을 최소 60으로 채우고, 풀려날 때 최소 40 (구금 중 굶어 죽던 문제 수정)
- **은신·변장:** 입력에 '숨어 지내' 등이 있으면 `turn_flags.laying_low` → `pass_time`에서 수배도 감소 4배. 변장(정규식 `DISGUISE_WORDS`)은 48시간, 목격된 범죄(수배도 상승)나 체포로 풀린다
- 알림 "🚔 경찰 — … (★)", "🏃 경찰에게서 벗어났다", 효과음(등장·체포 사이렌, 따돌림 성공음), 상태창 ★ 표시와 "변장 중"·"경찰이 쫓는 중" 배지

## 12. 경제 (`survival/economy.py`)
- **원칙:** 액수는 엔진이 정한다. GM 툴 `work`(job, hours) / `sell_item`(item) / `rent_room`(nights) / `gamble`(stake, game). `update_status`로 `money_source=work`·`sold` 돈을 주면 `gain_problem`이 막는다
- **일:** 야생 불가, 0~5시는 길거리 일만. 시급(마을/도시) labor 2/4, service 2.5/5, skilled 4/8, street 1.5/3.5 × (1 + 0.15 × 기술 Lv), 범죄자로 알려진 곳 ×0.5. 일한 시간만큼 `pass_time(work)`, 8시간마다 기술 Lv+1(최대 5)
- **팔기:** `ITEM_VALUES` 시세 × 도시 0.8 / 마을 0.6, 장물(`stolen_items`) ×0.5, 여권·표는 불가
- **숙소:** 1박 마을 $8 / 도시 $20(`pay`), 장면을 그 방 안으로. `in_lodging`(같은 곳·기간 안·실내)이면 경찰 등장 ×0.3, 은신(`laying_low`) 수배도 감소 6배
- **도박:** 판돈 ≤ $200·가진 돈, 45% 승리(+판돈), cinematic이면 3% 잭팟(+5배), 1시간
- 결과는 `turn_flags.economy` → 알림(💼 일·💰 판매·🛏 숙소·🎲 도박)과 효과음. 이 돈은 `money_log`에 `shown`으로 남아 "서술에 빠진 돈" 알림이 겹치지 않는다. 상태창 LIFE 칸(기술, 빌린 방)

## 13. 탈것 (`config.VEHICLES`, `survival/travel.py`)
- 종류: car, truck, motorbike, boat, bicycle, animal(말·낙타), plane. 속성: speed, range(연료로 가는 거리 / 연료 없는 탈것은 한 턴 최대 거리), sea, fuel, price, fuel_cost(km당), sold_in
- 얻기: `acquire_vehicle`(같은 턴 판정 성공, 연료 40~90%) 또는 `buy_vehicle`(정가, `pay`, 연료 가득). 탈것은 하나만(새로 얻으면 타던 것은 두고 감)
- 운전(`travel(method='drive')`): 연료 소모(연료 없는 탈것은 그대로), 자전거는 `walk` 활동(기력 소모). 연료가 떨어지면 **탈것은 남고** range 0으로 멈춘다. `refuel`: 마을·도시(경비행기는 도시)에서 돈으로 채우거나, 어디서든 소지품 연료통(`JERRYCAN_WORDS`)으로 +100km
- 운전 요청 판정(`tools.drive_requested`): 입력에 자기 탈것을 가리키는 말 + 이동 동사(타고·몰고·달린다·운전·간다 …)가 있으면 사이에 다른 말이 있어도 인정
- 국경: 운전으로 `country_code`가 바뀌면 `turn_flags.border`. 훔친 탈것이거나 수배도 ≥ `BORDER_CHECK_WANTED`(40)면 `pursuit`(국경 경비대, ★ 최소 3, 검문)를 만들어 다음 턴에 경찰과 같은 방식으로 판정

## 14. 업적과 여정 결산 (`survival/achievements.py`)
- 통계는 `end_turn`의 `record_turn` 한 곳에서 그 턴의 기록(`turn_flags`: moved·earned·paid·attempt·police·arrested·vehicle·border·economy)으로 모은다 → `state.stats`(turns, km, countries, earned, spent, crimes, criticals, escapes, arrests, vehicles, borders, work_hours, sold, jackpots, max_heat, peak_money)
- 업적 16개(`ACHIEVEMENTS`: 조건 함수). 새로 열리면 `state.achievements`, `turn_flags.achievements` → 알림 "🏆 업적 — …", 효과음(discover), 상태창 LIFE 칸
- 명예의 전당: 판이 바뀌어도 남는 업적별 횟수·처음 연 날. `HALL_ENABLED`(공유 모드에서는 끔), 테스트는 임시 경로
- 게임이 끝나면 `app.play`가 마지막 응답 뒤에 `run_summary`(결산 표와 이번 판의 업적)를 붙인다
