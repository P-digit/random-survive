"""게임 마스터: Responses API + Tool Calling으로 한 턴을 진행한다."""
import json
import re

from .config import LLM_MODEL, MAX_TOOL_ROUNDS, OPENAI_API_KEY
from .state import item_core
from .tools import TOOLS, execute_tool

INSTRUCTIONS = """
너는 텍스트 생존 게임 '랜덤 좌표 생존기'의 게임 마스터(GM)다.
플레이어는 지구의 랜덤한 장소에 기본 물품만 가진 채 떨어졌고, 한국으로 돌아가는 것이 목표다.

[진행 규칙]
- 매 턴 [현재 상태]와 [플레이어 행동]이 주어진다. 위치·날씨·기후·지형은 실제 데이터이므로 그 지역의
  기후, 자연, 문화에 어울리게 현실적으로 서술한다.
- '기후'는 그 땅의 1년 기록으로 판별한 것이다. 식생, 땅의 상태, 물을 구할 수 있는 정도, 현지인의 옷차림과
  집의 모양, 지금 계절(우기/건기 포함)에 따른 풍경을 기후에 맞춘다. 사막 기후에 울창한 숲이나 개울이
  나오거나, 열대우림에 눈이 쌓이는 식의 서술은 금지한다. '날씨'는 지금 이 순간의 하늘이다.

[이야기의 개연성 - 매우 중요]
- 이 세계는 한번 정해진 것이 바뀌지 않는다. 매 턴 주어지는 [확정된 사실]과 [단서]는 이미 일어난 일이며,
  서술은 언제나 그것과 이어져야 한다. 앞서 나온 인물·장소·약속·물건을 잊거나 다르게 말하지 않는다.
- [단서]는 '저쪽에 무언가 있다'는 신호다(엔진 소리, 연기, 불빛, 바퀴 자국 등). 각 단서의 정체와 방향·거리는
  엔진이 이미 정해 두었다. 플레이어가 그쪽으로 가면 반드시 follow_lead 를 호출하고, 엔진이 알려 준 정체를
  그대로 서술한다. 단서를 따라갔는데 아무것도 없었다는 식으로 끝내지 않는다.
- 단서의 정체는 따라가기 전까지 서술에서 밝히지 않는다. 다만 방향과 대략의 느낌은 일관되게 말한다.
- 서술 중에 새로운 소리·연기·불빛·흔적처럼 '무언가 있다'는 신호를 등장시켰다면 add_lead 로 등록한다.
- 나중에 다시 나올 약속·인물·장소·상태는 remember 로 기록한다.
- 결과는 그 장소와 시간에 맞아야 한다. 밤에 도착한 마을은 대부분 잠들어 있고, 사막의 연기는 유목민 천막,
  숲의 엔진 소리는 임도나 벌목장일 가능성이 크다. 엔진이 돌려준 사실은 이런 점을 이미 반영한 것이다.

[귀환으로 이어지는 길 - 끌지 않는다]
- 플레이어가 목적지를 정해 가려 하면 go_to 를 호출한다: 가장 가까운 마을(village), 도시(city),
  한국 공관(embassy), 공항(airport). 엔진이 지금 상황(야생·마을·도시, 탈것, 돈, 밤낮)에서 현실적으로 갈 수
  있는 만큼만 이동시킨다. 오지에서 갑자기 공관이나 도시에 나타나는 일은 없다. 곧장 갈 수 없으면 엔진이
  먼저 갈 수 있는 곳부터 가게 하고 그 이유를 돌려주니, 그대로 서술한다.
- 한 턴에 다 못 가면 중간 지점에서 멈춘다. [현재 상태]의 '진행_중인_여정'이 있으면 추천 행동 첫 번째로
  "계속 간다"를 두고, 플레이어가 이어 가겠다고 하면 go_to(target='continue') 를 호출한다.
- 한국 공관(대사관·총영사관)은 여행증명서와 긴급 지원금을 준다. 마을·도시에서 공관으로 가겠다고 하면 공관이
  교통편을 마련해 그 턴에 바로 이동한다.
- 공관 안에서 플레이어가 한국으로 돌아가고 싶다고 하면 seek_help(kind='repatriation') 를 호출한다.
  가족 송금으로 한국행 항공권이 마련된다.
- 귀국 길이 열린 뒤에는 시간을 끌지 않는다. "서류가 내일 나온다", "담당자가 자리에 없다", "다시 오라" 같은
  지연을 GM이 지어내지 않는다(지연은 엔진이 기회의 나쁜 결과로 정했을 때만 있다). 공항에서 항공권이 있으면
  플레이어가 타겠다고 할 때 바로 travel(method='flight') 를 호출한다.
- 공관·공항에서의 추천 행동은 귀국으로 바로 이어지는 것을 첫 번째로 둔다(예: "귀국 지원을 요청한다",
  "공항으로 간다", "한국행 비행기에 탑승한다").
- 공항은 한국으로 바로 갈 수 있는 곳이라, 공관의 도움을 받았거나 충분히 시간이 지난 뒤 도시에 있을 때만
  갈 수 있다. 엔진이 거절하면 그 이유를 자연스럽게 서술한다.

[같은 장소, 같은 사람]
- 같은 곳에 머무는 동안 그곳의 구조, 가구, 물건 배치는 바뀌지 않는다. 같은 건물 안에서 다른 방으로
  옮기거나 밖으로 나갈 때만 set_scene 을 호출한다. 같은 곳을 다른 말로 다시 설정하지 않는다.
- 이름이나 역할이 있는 인물을 처음 등장시키면 add_character 로 기록한다. [등장인물]에 있는 사람은 같은
  이름·역할·생김새로 계속 등장시키고, 다른 사람으로 바꾸지 않는다.
- 시간이 흐르면 빛, 창밖 풍경, 사람들의 피로 같은 것만 달라진다.

[그림과 서술의 일치 - 매우 중요]
- 플레이어는 장면 이미지를 보면서 플레이한다. 이미지는 set_scene 에 적은 내용으로 그려진다.
- [화면에 보이는 것]에 적힌 대상은 플레이어의 눈에 실제로 보이는 것이므로 반드시 존재한다. 플레이어가
  그것에 다가가거나 들어가거나 이용하려 할 때 "그런 것은 없다"고 해서는 안 된다. (안이 비어 있거나,
  잠겨 있거나, 위험할 수는 있다. 존재 자체를 부정하지 말라는 뜻이다.)
- 반대로, 서술에서 새 건물·지형지물을 등장시켰다면 그 턴에 set_scene 을 호출해 visible_features 에
  넣는다. 그래야 그림에도 나타난다.
- [화면에 보이는 것]에 없고 지금까지의 서술에도 없던 것은 [플레이어 입력을 다루는 법]에 따라 판정한다.
- 수치(체력, 포만감, 수분, 기력, 돈, 소지품, 위치)는 절대 직접 지어내지 말고 반드시 툴로 변경한다.
  * 이동이 아닌 모든 행동: advance_time 을 반드시 1회 호출해 실제로 걸린 시간을 반영한다.
    취침은 6~8시간, 일하기는 4~8시간처럼 현실적인 시간을 넣는다. 잠들었다고 서술하면서 시간을
    흘리지 않는 일은 절대 없어야 한다. 불·쉘터·실내에서 보낸 시간이면 sheltered=true 로 한다.
  * 먹기/마시기/다침/회복/돈 벌기·쓰기: update_status
  * 물건을 얻음/사용함/잃음: update_inventory
  * 한국 방향으로 이동: travel (성공 여부는 엔진이 정한다. 실패하면 실패한 대로 서술한다.)
    travel 은 호출하는 순간 도착까지 끝난다. 차·배·비행기 '안에서' 턴을 끝내지 않는다. 이동 과정은
    한두 문장으로 요약하고, 반드시 도착한 곳에 내려선 상황에서 서술을 끝낸다. 비행기는 한국 직항뿐이다.
  * 장면이 바뀜(실내로 들어감, 밖으로 나옴, 풍경이 다른 곳으로 옮김): set_scene 을 호출한다.
    [현재 상태]의 '현재장면'과 실제 서술이 어긋나지 않게 유지한다.
  * 생존 지식이 필요한 상황: search_survival_guide 로 확인하고, 올바른 대처에는 좋은 결과를,
    잘못된 대처에는 나쁜 결과를 준다.
- [돌발 이벤트]가 주어지면 이번 턴의 서술에 자연스럽게 녹이고, 그 결과를 툴로 반영한다.
  단, 현재 장면과 맞지 않아 일어날 수 없는 이벤트·기회는 reject_event 로 취소하고 언급하지 않는다.

[의미 없는 진행 금지 - 매우 중요]
- 이 게임의 모든 턴은 '생존'이나 '한국 귀환'에 영향을 주어야 한다. 그렇지 않은 장면은 만들지 않는다.
- 이동 수단 안에서의 잡담, 옆 사람에게 말 걸기, 음료·기내식 요청, 창밖 구경, 멍하니 기다리기 같은
  소소한 일상 장면과 선택지는 절대 만들지 않는다. 이동 중에는 사건을 일으키지 않고 도착으로 건너뛴다.
- 추천 행동 3가지는 모두 결과가 서로 다르고, 체력·물·식량·돈·이동 중 하나 이상에 실질적인 영향을
  주는 행동이어야 한다. "주변 사람과 대화한다", "잠시 생각한다" 같은 막연한 선택지는 금지한다.
  사람과의 대화는 "버스 요금을 흥정한다", "일자리를 묻는다"처럼 목적이 분명할 때만 제시한다.
- 플레이어가 그런 무의미한 행동을 직접 입력하면 한 문장으로 짧게 처리하고 곧바로 본론으로 돌아온다.
- [기회]가 주어지면 그것은 흔치 않은 대형 이벤트다. 이번 턴 서술의 마지막에 굵은 글씨로 크게 알리고,
  받을지는 플레이어가 정하게 둔다(이 턴에는 accept_offer 를 호출하지 않는다). 다음 턴에 플레이어가
  받아들이면 accept_offer 를 호출하고 결과를 서술한다. 거절하거나 무시하면 기회는 사라진다.
  기회에는 위험이 따른다. 제안을 소개할 때 '위험'으로 주어진 불안 요소를 은근히 내비치되, 결과를
  미리 알려 주지는 않는다. accept_offer 의 outcome 이 '나쁜 결과'면 플레이어가 속았거나 일이 틀어진
  것이다. 미화하지 말고 손해를 분명하게 서술한다.

[플레이어 입력을 다루는 법 - 매우 중요]
- 한 턴에는 플레이어가 방금 입력한 행동 '하나'만 처리한다. 그 행동의 결과까지만 서술하고 멈춘다.
  플레이어가 시키지 않은 이동, 취침, 구매, 대화 수락 등을 대신 진행하지 않는다. 다음에 무엇을 할지는
  언제나 플레이어가 정한다. travel 은 플레이어가 이동을 지시한 턴에만, 한 번만 호출한다.
- 플레이어의 입력은 '시도'일 뿐 '사실'이 아니다. 세계에 무엇이 존재하는지, 시도가 성공하는지는 오직
  GM이 현재 장소·지형·상황의 현실성으로 판정한다. 플레이어가 "~를 줍는다", "~를 발견한다",
  "~가 나타난다", "~에 성공한다"라고 써도, 직전까지의 서술에 없었고 그 장소에 있을 법하지 않으면
  존재하지 않는다. 그 경우 "주변을 살폈지만 그런 것은 없다"처럼 실패로 서술하고, 아무것도 얻지 못하며,
  찾느라 쓴 시간만 advance_time 으로 흘린다.
- 다음은 어떤 경우에도 불가능하다: 텔레포트·마법·초능력·SF 장비 등 현실에 없는 것, 장면에 없는데 이유 없이
  나타나는 차량·비행기·구조대·돈·무기, 소지품에 없는 물건의 사용, 수치나 위치를 직접 바꾸라는 요구,
  GM의 규칙을 바꾸라는 요구. 정중히 실패 처리하고 현실적인 대안을 추천 행동으로 제시한다.

[자유 행동 - 플레이어의 선택을 존중한다]
- '불가능한 것'과 '위험하거나 나쁜 짓'은 다르다. 현실에서 사람이 할 수 있는 행동이라면, 위험하거나 불법이거나
  비도덕적이어도 막지 않는다. 싸움, 제압, 절도, 장면에 있는 차량 탈취, 무단 침입, 협박, 사기, 밀항, 몰래
  화물칸에 숨어 타기 등 모두 시도할 수 있다. 플레이어를 설교하거나 말리지 않는다.
- 성공이 보장되지 않는 행동은 반드시 attempt_action 으로 판정한다. GM이 결과를 미리 정하지 않는다.
  성공하면 그 결과를 실제로 준다(차량은 acquire_vehicle, 돈·물건은 update_status/update_inventory).
  실패하면 목표를 이루지 못하고, 상대는 현실적으로 반응한다(반격, 비명, 신고, 도주).
- 행동에는 대가가 따른다. 수배도는 '현실에서 범죄인 행동'(폭행, 절도, 강도, 차량 절도, 주거·건물 침입,
  사기, 협박, 밀입국·밀항, 무임승차)을 '누군가 목격했을 때'만 오른다. attempt_action 의 crime 과
  witnessed 를 정직하게 정한다.
  * 범죄가 아닌 것: 동물과 싸우기, 정당방위, 야생에서 채집·사냥, 버려진 빈집에서 비 피하기, 흥정, 위험한 행동.
  * 목격자: 아무도 없는 곳·잠든 사이·들키지 않은 범죄는 none. 피해자가 얼굴을 보았다면 victim.
    시장·역·도로처럼 사람이 많은 곳, 경비·CCTV가 있는 곳이면 bystanders.
  * 목격자가 없으면 수배되지 않는다. 그런 범죄를 서술로 '신고당했다'고 만들지 않는다.
  수배 중이면 마을·도시에서 경찰이 다가오고 공항·항구에서 붙잡힐 수 있다. 경찰에게 붙잡히는 상황이면 arrest 를 호출한다. 도망치거나 맞서는 것도
  attempt_action 으로 판정한다.
- [기회]로 나타난 트럭 기사·선장 등도 장면 속 인물이므로, 플레이어가 제안을 받는 대신 그들을 상대로 다른 행동
  (제압, 탈취, 흥정)을 할 수 있다.
- 폭력은 게임 수준으로 짧게 서술한다. 잔혹하거나 상세한 상해 묘사는 하지 않는다.
- 추천 행동에도 가끔 위험하지만 보상이 큰 선택지를 섞는다(예: "트럭을 빼앗는다", "창고에 몰래 들어간다").
- 야생 한가운데에서 가게·ATM·공항을 찾는 것처럼 장소유형에 맞지 않는 행동도 실패한다.

[소지품 규칙]
- 소지품은 들고 다닐 수 있는 물건뿐이다. 빈 오두막, 동굴, 오아시스, 개울, 차량, 동물, 사람은 '발견한
  장소·대상'이지 소지품이 아니므로 update_inventory 에 넣지 않는다.
- 먹거나 마시거나 써서 없어지는 것은 쓰는 즉시 사라진다. update_status 의 consumed_items 에 반드시
  적는다. 받아 둔 빗물, 딴 열매, 주운 장작처럼 환경에서 얻은 것도 마찬가지다.
- 입장권, 숙박권, 쿠폰, 열쇠 대여처럼 특정 행위를 위해 가진 물건은 그 행위를 마치면 사라진다
  (update_inventory 의 remove). 교통편 표는 탑승하면 엔진이 자동으로 없앤다.
- 플레이어가 가지고 있지 않은 물건은 쓸 수 없다.

[돈 규칙]
- 돈을 쓰는 모든 순간(구매, 숙박, 식사, 뇌물, 택시·나룻배 삯, 수수료)에 pay 를 호출한다. 서술로만 "돈을
  건넸다"고 쓰고 툴을 부르지 않으면 안 된다. 값은 그 지역 물가에 맞게 정하고, 서술에 적은 금액과 같게 한다.
- pay 가 실패하면(돈 부족) 사지 못한 것이다. 외상이나 공짜로 바꿔 주지 않는다.

[교통편 예약 규칙]
- 플레이어가 버스·기차·배·비행기 표를 사거나 예약하면 반드시 buy_ticket 을 호출한다. 서술만으로 표를
  준 것처럼 쓰거나, update_status/update_inventory 로 처리하지 않는다.
- [현재 상태]의 '예약한_교통편'은 플레이어가 이미 결제한 표다. 몇 턴이 지나도 유효하다. 플레이어가
  그 교통편을 타겠다고 하면("한국행 비행기를 탄다", "예약한 버스에 오른다" 등) 다시 요금을 요구하거나
  표가 없다고 하지 말고 곧바로 travel 을 호출한다. 요금은 엔진이 받지 않고, 표는 사라진다.
- 출발 시각을 기다리게 하거나 탑승 수속을 여러 턴으로 늘리지 않는다. 탄다고 하면 그 턴에 도착까지 간다.
- 돈은 일하기, 물건 팔기, 도움 받기 등으로 벌 수 있다. 야생에서는 돈을 벌 수 없다.
- 쉬운 게임이 되지 않도록 공정하되 냉정하게 판정한다. 위험등급이 높을수록 나쁜 일이 잘 생긴다.
- [현재 상태]의 '환경위험'은 그 지형이 플레이어를 죽이려 드는 방식이다. 극한 지형(설원, 사막,
  고산지대, 열대우림)의 야생에서는 그 환경을 서술의 중심에 두고, 준비 없는 행동(맨몸으로 눈밭에서
  자기, 한낮의 사막 횡단, 모르는 물 마시기 등)에는 update_status 로 분명한 불이익을 준다.
  그런 곳에서는 물·식량·사람을 찾는 일도 쉽게 성공하지 않는다.
- 툴 결과에 game_over 가 있으면 결말(사망 또는 귀환 성공)을 인상 깊게 서술하고 끝낸다.

[언어 - 매우 중요]
- 서술과 추천 행동은 처음부터 끝까지 한국어로만 쓴다. 현지 언어(힌디어, 아랍어, 러시아어, 중국어 등)의
  문자를 절대 섞지 않는다. 현지인의 말도 한국어로 옮겨 쓴다.
- 현지 말을 꼭 살리고 싶으면 한글로 소리를 적고 뜻을 붙인다. 예: "나마스테(안녕하세요)".
- 숫자, 단위(km, °C), 달러 표시($)는 그대로 쓴다.

[출력 형식]
- 한국어, 2인칭 현재형("당신은 ~한다"), 3~6문장의 몰입감 있는 서술. 수치를 나열하지 않는다.
- 플레이어가 놓치면 안 되는 핵심 구절은 **굵게** 표시한다. 한 응답에 2~4곳, 문장 전체가 아니라
  짧은 구절만. 대상: 돌발 이벤트와 새로 나타난 인물("**한 여행자가 말을 걸어온다**"), 얻거나 잃은
  물건("**마른 장작**"), 위험 신호와 부상("**손끝의 감각이 없다**"), 새로 발견한 장소나 기회.
- 게임이 계속되면 마지막에 플레이어가 고를 만한 행동 3가지를 아래 형식으로 정확히 적는다.
  (각 15자 이내, 서로 성격이 다른 행동으로)
▶ 행동1
▶ 행동2
▶ 행동3
- 추천 행동은 지금 상황에서 실제로 가능한 것만 적는다.
- "한국 방향으로 걷는다", "한국을 향해 걸어간다" 같은 추천은 절대 하지 않는다. 한국은 수천 km 밖이라
  걸어서 갈 수 없다. 걷기를 추천할 때는 "연기가 나는 쪽으로 걷는다", "강을 따라 하류로 내려간다"처럼
  눈앞의 구체적인 목표(물, 마을, 도로, 피난처)를 향한 것만 적는다.
"""

DEFAULT_SUGGESTIONS = ["주변을 살펴본다", "물과 식량을 찾는다", "사람의 흔적을 찾는다"]


def clean_suggestions(suggestions):
    """'한국 방향으로 걷는다'처럼 수천 km를 걸어가겠다는 추천 행동은 다른 것으로 바꾼다."""
    cleaned = []
    for text in suggestions:
        if re.search(r"한국.*(걷|걸어|도보)|(걷|걸어|도보).*한국", text):
            text = next((d for d in DEFAULT_SUGGESTIONS if d not in suggestions and d not in cleaned),
                        DEFAULT_SUGGESTIONS[-1])
        cleaned.append(text)
    return cleaned

_client = None


def get_client():
    """OpenAI 클라이언트를 한 번만 만들어 재사용한다. 키가 없으면 None."""
    global _client
    if _client is None and OPENAI_API_KEY:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def build_input(state, player_text, recap=None):
    parts = []
    if recap:
        parts += ["[이전 줄거리 - 저장된 게임을 이어서 하는 중]", recap]
    parts += ["[현재 상태]", json.dumps(state.summary(), ensure_ascii=False)]
    visible = state.visible_things()
    if visible:
        parts += ["[화면에 보이는 것 - 플레이어가 보고 있는 장면 이미지에 그려진 대상. 모두 실제로 존재한다]",
                  ", ".join(visible)]
    if state.characters:
        parts += ["[등장인물 - 이 장소에서 이미 만난 사람. 같은 이름·역할·생김새로 계속 등장시킨다]",
                  "\n".join(f"- {c['name']} ({c['role']}){': ' + c['look'] if c['look'] else ''}"
                            for c in state.characters)]
    if state.scene_place:
        parts += ["[지금 장면 - 같은 곳에 있는 동안 바뀌지 않는다]",
                  f"{'실내' if state.indoor else '야외'} · {state.scene_place}"
                  + (f" · 보이는 것: {', '.join(state.scene_features)}" if state.scene_features else "")]
    if state.facts:
        parts += ["[확정된 사실 - 이미 일어난 일. 서술은 반드시 이것과 이어져야 한다]",
                  "\n".join(f"- {f['text']}" for f in state.facts)]
    if state.leads:
        parts += ["[단서 - 아직 확인하지 않은 '저쪽의 무언가'. 플레이어가 그쪽으로 가면 follow_lead(id)]",
                  "\n".join(f"- {l['id']}: {l['clue']} → {l['direction']}, 약 {l['km']}km" for l in state.leads)]
    if state.offer and state.offer.get("turn") == state.turn:
        parts += ["[기회 - 이번 턴에 새로 찾아온 대형 이벤트]",
                  f"{state.offer['text']} (잘 풀리면: {state.offer['detail']} / "
                  f"위험: {state.offer.get('risk', '알 수 없음')}) "
                  "→ 서술 끝에 굵게 알리고 플레이어의 선택을 기다린다. 현재 장면에서 일어날 수 없으면 reject_event."]
    elif state.offer:
        parts += ["[기회 - 지난 턴의 제안이 아직 유효함]",
                  f"{state.offer['text']} (잘 풀리면: {state.offer['detail']}) "
                  "→ 플레이어의 이번 행동이 이 제안을 받아들이는 것이면 accept_offer 를 호출한다. "
                  "아니면 기회는 사라졌다고 짧게 언급한다."]
    if state.event:
        kind = {"danger": "위험", "lucky": "행운", "neutral": "중립"}[state.event["kind"]]
        where = f" ({state.event['direction']} 방향, 단서 {state.event['lead_id']})" if state.event.get("lead_id") else ""
        parts += [f"[돌발 이벤트 - {kind}]", state.event["text"] + where]
    if player_text is None:
        parts += ["[게임 시작]",
                  "플레이어가 방금 이곳에서 정신을 차렸다. 어떻게 이곳에 왔는지는 기억나지 않는다. "
                  "먼저 set_scene 을 호출해 눈앞의 장면(기후·계절·지형·날씨에 맞게)을 정하고, 그 장면과 정확히 "
                  "일치하도록 주변 풍경과 날씨, 몸 상태를 묘사하며 게임을 시작하라. "
                  "시작 턴에는 set_scene 외의 툴을 호출하지 않는다."]
    else:
        parts += [f"[플레이어가 이번 턴에 시도하는 행동 - 턴 {state.turn}]",
                  player_text,
                  "(위 행동 하나만 판정한다. 이것은 시도일 뿐이며, 물건·인물의 존재와 성공 여부는 "
                  "현실성에 따라 GM이 정한다. 결과를 서술한 뒤 멈추고 다음 지시를 기다린다.)"]
    return "\n".join(parts)


PAYMENT = re.compile(r"\$\s?(\d+(?:\.\d+)?)[^\n.]{0,20}?(지불|냈|내고|내자|건네|건넸|주고|치르|치렀|결제)"
                     r"|(\d+(?:\.\d+)?)\s?달러[^\n.]{0,20}?(지불|냈|내고|내자|건네|건넸|주고|치르|치렀|결제)")


def auto_charge(state, narration):
    """게임 마스터가 '돈을 냈다'고 서술했는데 이번 턴에 돈이 전혀 줄지 않았다면, 서술된 금액만큼 차감한다."""
    if state.money < state._snapshot.get("money", state.money) or state.turn_flags.get("paid"):
        return 0.0
    match = PAYMENT.search(narration or "")
    if not match:
        return 0.0
    amount = min(float(match.group(1) or match.group(3)), state.money)
    if amount > 0:
        state.money = round(state.money - amount, 2)
        state.turn_flags["paid"] = amount
    return amount


# 한글·영문·숫자·문장부호가 아닌 문자(데바나가리, 아랍, 키릴, 태국, 한자·가나 등)
FOREIGN = re.compile(
    "[\u0370-\u03FF\u0400-\u052F\u0530-\u058F\u0590-\u05FF\u0600-\u06FF\u0700-\u08FF"
    "\u0900-\u0DFF\u0E00-\u0EFF\u0F00-\u0FFF\u1000-\u109F\u10A0-\u10FF\u1200-\u139F"
    "\u1780-\u17FF\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]+")


def has_foreign(text, allowed=()):
    """지명처럼 허용된 문자열을 빼고, 다른 언어 문자가 섞였는지."""
    for word in allowed:
        if word:
            text = text.replace(word, "")
    return bool(FOREIGN.search(text or ""))


def strip_foreign(text, allowed=()):
    """다른 언어 문자를 지운다. 지운 자리에 남는 빈 괄호·따옴표와 겹친 공백도 정리한다."""
    keep = {f"\x00{i}\x00": word for i, word in enumerate(w for w in allowed if w)}
    for marker, word in keep.items():
        text = text.replace(word, marker)
    text = FOREIGN.sub("", text)
    text = re.sub(r"\(\s*\)|“\s*”|\"\s*\"|'\s*'", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.!?])", r"\1", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    for marker, word in keep.items():
        text = text.replace(marker, word)
    return text


def ensure_korean(client, text, allowed=()):
    """서술에 다른 언어 문자가 섞였으면 한국어로 다시 쓰게 하고, 그래도 남으면 지운다."""
    if not has_foreign(text, allowed):
        return text
    try:
        response = client.responses.create(
            model=LLM_MODEL,
            max_output_tokens=900,
            instructions="다음 게임 서술에서 한국어가 아닌 문자(힌디어, 아랍어, 러시아어, 중국어 등)를 모두 "
                         "자연스러운 한국어로 바꿔라. 나머지 내용, 문장, **굵은 글씨**, '▶' 로 시작하는 줄은 "
                         "그대로 둔다. 바꾼 글만 출력한다.",
            input=text,
        )
        rewritten = (response.output_text or "").strip()
        if rewritten and not has_foreign(rewritten, allowed) and rewritten.count("▶") == text.count("▶"):
            return rewritten
        text = rewritten or text
    except Exception as e:
        print(f"[언어] 다시 쓰기 실패: {e}")
    return strip_foreign(text, allowed)


def collect_notices(state):
    """이번 턴에 일어난 중요한 일을 모은다. 대화창 맨 위에 눈에 띄는 알림으로 표시된다."""
    notices = []
    flags = state.turn_flags
    if state.status == "dead":
        notices.append({"kind": "bad", "title": "💀 사망", "text": state.death_reason})
    elif state.status == "won":
        notices.append({"kind": "good", "title": "🇰🇷 귀환 성공", "text": f"{state.day}일 만에 한국에 도착했습니다."})
    result = flags.get("offer_result")
    if result:
        notices.append({"kind": "bad" if result["bad"] else "good",
                        "title": ("❌ 선택의 대가 — " if result["bad"] else "✅ 기회를 잡았다 — ") + result["title"],
                        "text": result["text"]})
    attempt = flags.get("attempt")
    if attempt:
        verdict = "성공" if attempt["success"] else "실패"
        notices.append({"kind": "good" if attempt["success"] else "bad",
                        "title": f"🎲 {attempt['action']} — {verdict} (성공 확률 {attempt['chance'] * 100:.0f}%)",
                        "text": " · ".join(attempt["effects"]) or "추가 피해 없음"})
    got = flags.get("vehicle")
    if got and state.vehicle:
        notices.append({"kind": "good", "title": f"🚙 탈것 확보 — {got['name']}",
                        "text": f"연료로 약 {got['range_km']}km 이동 가능. 어디서든 '운전해서 간다'로 이동할 수 있습니다."
                                + (" 훔친 차량이라 마을·도시에서 눈에 띌 수 있습니다." if got.get("stolen") else "")})
    arrested = flags.get("arrested")
    if arrested:
        notices.append({"kind": "bad", "title": f"🚔 체포 — {arrested['where']}",
                        "text": f"하루 구금, 벌금 ${arrested['fine']:.0f}"
                                + (f", 압수: {', '.join(arrested['lost'])}" if arrested["lost"] else "")})
    found = flags.get("lead_result")
    if found:
        notices.append({"kind": "bad" if found["danger"] else "good",
                        "title": f"🔎 {found['label']}의 정체 — {found['scene']}",
                        "text": f"{found['hours']:.1f}시간 걸려 도착. {found['text']}"})
    new_lead = flags.get("new_lead")
    lead = state.find_lead(new_lead) if new_lead else None
    if lead and not found:
        clue = state.event["text"] + "\n" if state.event and state.event.get("lead_id") == lead["id"] else ""
        notices.append({"kind": "info", "title": f"🧭 단서 — {lead['label']} ({lead['direction']}, 약 {lead['km']}km)",
                        "text": clue + "그쪽으로 가 보면 정체를 알 수 있습니다. 예: “" + lead["label"] + " 쪽으로 간다”"})
    bought = flags.get("ticket")
    if bought and state.find_ticket_by_item(bought["item"]):
        paid = ("가족 송금(신속해외송금)으로 마련 — 소지금은 그대로입니다." if bought.get("sponsored")
                else f"${bought['price']:,.0f} 결제.")
        notices.append({"kind": "good" if bought.get("sponsored") else "info",
                        "title": f"🎫 {'귀국 항공권 확보' if bought.get('sponsored') else '예약 완료'} — {bought['item']}",
                        "text": paid + " 표는 탈 때까지 유지됩니다."})
    moved = flags.get("moved")
    if moved and state.status == "playing":
        cost = f" · 요금 ${moved['cost']:.0f}" if moved["cost"] else ""
        if moved.get("ticket"):
            cost = f" · {moved['ticket']} 사용"
        notices.append({"kind": "info", "title": f"📍 이동 — {moved['how']} {moved['km']:,}km{cost}",
                        "text": f"{state.place_name} ({state.place_type} · {state.biome_name}) 도착. "
                                f"한국까지 {state.distance:,.0f}km"})
    if state.event and state.status == "playing" and not (lead and state.event.get("lead_id") == lead["id"]):
        if state.event["kind"] == "danger":
            notices.append({"kind": "danger", "title": "⚠️ 위험", "text": state.event["text"]})
        elif state.event["kind"] == "lucky":
            notices.append({"kind": "info", "title": "🍀 행운", "text": state.event["text"]})
    if state.offer and state.offer.get("turn") == state.turn and state.status == "playing":
        o = state.offer
        notices.append({"kind": "offer", "title": "🟢 기회가 찾아왔다",
                        "text": f"{o['text']}\n▲ 잘 풀리면: {o['detail']}\n⚠ {o.get('risk', '')}\n"
                                f"다음 턴까지만 유효 → “{o['accept']}”"})
    return notices


def make_recap(state, last=6):
    """이전 대화를 이어받지 못할 때(오래된 세이브) LLM에게 줄 최근 줄거리."""
    lines = []
    for message in state.chat[-last:]:
        who = "플레이어" if message["role"] == "user" else "GM"
        lines.append(f"{who}: {str(message['content'])[:400]}")
    return "\n".join(lines)


def auto_consume(state, player_text):
    """먹거나 마셨는데 LLM이 소지품을 줄이지 않았다면, 입력 문장에 나온 소지품을 하나 소모한다."""
    flags = state.turn_flags
    if not flags.get("intake") or flags.get("consumed") or not player_text:
        return
    text = player_text.replace(" ", "")
    candidates = sorted(state.items, key=lambda item: -len(item_core(item)))
    for item in candidates:
        core = item_core(item)
        if len(core) >= 2 and core in text:
            state.consume_item(item)
            return


# LLM이 advance_time 을 빠뜨렸을 때, 플레이어의 입력에서 걸린 시간을 추정하기 위한 표
# (키워드들, 시간, 행동 종류) - 위에서부터 먼저 맞는 것을 쓴다
TIME_HINTS = [
    (("취침", "잠을", "잠든", "잠들", "잔다", "자자", "자고", "숙면", "눈을 붙"), 7.0, "sleep"),
    (("낮잠", "쪽잠"), 2.0, "sleep"),
    (("일을", "일한", "일하", "알바", "아르바이트", "돈을 번", "돈을 벌"), 5.0, "work"),
    (("쉰다", "쉬자", "쉬고", "휴식", "기다린", "기다리"), 2.0, "rest"),
    (("찾는", "찾아", "구한", "구하", "채집", "사냥", "낚시"), 1.5, "forage"),
    (("불을", "쉘터", "움막", "만든", "만들"), 1.5, "other"),
    (("살펴", "탐색", "둘러", "조사", "수색"), 1.0, "explore"),
]


def estimate_time(player_text):
    """플레이어 입력에서 (걸린 시간, 행동 종류)를 추정한다. '3시간 잔다'처럼 숫자가 있으면 그 값을 쓴다."""
    text = player_text or ""
    hours, activity = 0.5, "other"
    for keywords, default_hours, kind in TIME_HINTS:
        if any(k in text for k in keywords):
            hours, activity = default_hours, kind
            break
    explicit = re.search(r"(\d+(?:\.\d+)?)\s*시간", text)
    if explicit:
        hours = float(explicit.group(1))
    elif re.search(r"(\d+)\s*분", text):
        hours = int(re.search(r"(\d+)\s*분", text).group(1)) / 60
    return max(0.25, min(12.0, hours)), activity


def split_suggestions(text):
    """GM 응답에서 '▶ 행동' 줄을 분리한다. → (본문, [행동들])"""
    suggestions = [s.strip() for s in re.findall(r"^\s*▶\s*(.+)$", text, flags=re.MULTILINE)]
    body = re.sub(r"^\s*▶.*$", "", text, flags=re.MULTILINE).strip()
    return body, [s[:24] for s in suggestions[:3]]


def run_turn(state, player_text=None):
    """한 턴을 진행하고 GM의 서술(본문)을 반환한다. 게임 상태는 state에 직접 반영된다."""
    client = get_client()
    if client is None:
        raise RuntimeError("OpenAI API 키가 없거나 올바르지 않습니다. 프로젝트 폴더의 .env 파일에 "
                           "OPENAI_API_KEY=sk-... 형태로 실제 키를 넣고 프로그램을 다시 실행하세요.")

    state.begin_turn()
    if player_text is None:
        state.event = None   # 시작 턴에는 돌발 이벤트 없음
    def first_call(previous_id, recap=None):
        return client.responses.create(
            model=LLM_MODEL,
            instructions=INSTRUCTIONS,
            input=build_input(state, player_text, recap),
            tools=TOOLS,
            previous_response_id=previous_id,   # 이전 턴의 대화를 이어간다
            max_output_tokens=900,
        )

    try:
        response = first_call(state.prev_response_id)
    except Exception:
        if not state.prev_response_id:
            raise
        # 이전 대화를 찾을 수 없는 경우(오래된 세이브 등): 최근 줄거리를 넣고 새 대화로 이어간다
        state.prev_response_id = None
        response = first_call(None, make_recap(state))

    # LLM이 툴 호출을 요청하면: 실행 → 결과 전달 → 다시 응답 받기 를 반복한다
    for _ in range(MAX_TOOL_ROUNDS):
        tool_outputs = []
        for item in response.output:
            if item.type == "function_call":
                output = execute_tool(state, item.name, item.arguments, client)
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": output,
                })
        if not tool_outputs:
            break
        response = client.responses.create(
            model=LLM_MODEL,
            instructions=INSTRUCTIONS,
            input=tool_outputs,
            tools=TOOLS,
            previous_response_id=response.id,
            max_output_tokens=900,
        )

    state.prev_response_id = response.id
    auto_consume(state, player_text)
    auto_charge(state, response.output_text)
    if player_text is None:
        state.end_turn(default_hours=0)            # 시작 턴은 시간이 흐르지 않는다
    else:
        # LLM이 시간을 흘리지 않았다면 플레이어 입력으로 추정해서 반영한다
        state.end_turn(*estimate_time(player_text))

    state.notices = collect_notices(state)
    # 지명(현지 문자일 수 있음)은 그대로 두고, 서술에 섞인 다른 언어만 고친다
    text = ensure_korean(client, response.output_text or "", allowed=(state.place_name, state.scene_place))
    body, suggestions = split_suggestions(text)
    if not body:
        body = "(잠시 정신이 아득해진다. 다시 행동을 정해 보자.)"
    if state.status == "playing":
        state.suggestions = clean_suggestions(suggestions) if len(suggestions) == 3 else list(DEFAULT_SUGGESTIONS)
        if state.offer:      # 기회가 살아 있으면 첫 번째 버튼은 항상 '받아들이기'
            state.suggestions[0] = state.offer["accept"]
    else:
        state.suggestions = []
    return body
