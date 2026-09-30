# 차단 조회 SQL 후보 검증

동일한 H2 데이터에서 양방향 차단 OR 조건을 두 NOT EXISTS의 AND로 나눴다. API/JAR/백엔드 소스/인덱스 변경은 수행하지 않았다. SQL 실행당 평균은 각10회이며 매번 고유 주석으로 새 명령을 만들어 결과 캐시 재사용을 피했다. 별도3회 워밍업은 서버/JIT 대상이며 HTTP/HTML/SQL 컴파일 시간은 함께 보존한 console round trip에 포함된다. 아래 SQL 시간은 H2 실행 통계다.

| 경로 | SQL | 기존 평균 ms | 후보 평균 ms | SQL 시간 감소 % | BLOCK 전체 스캔 기존/후보 |
|---|---|---:|---:|---:|---|
| list-authenticated | content | 357.886 | 15.802 | 95.58 | 있음/없음 |
| list-authenticated | count | 126.750 | 1.838 | 98.55 | 있음/없음 |
| search-frequent-authenticated | content | 121.337 | 4.723 | 96.11 | 있음/없음 |
| search-frequent-authenticated | count | 117.804 | 2.635 | 97.76 | 있음/없음 |

## 정합성과 범위

- 회원2·3·4·31에 대해 원래/후보 SQL의 모든 content 행과 정렬·모든 count 값을 대조했다.16개 query shape/member 비교가 모두 같았다. 회원3은 기본/검색 모두 content0건·count0건으로 차단 데이터가 포함된 경우도 비교했다.
- 기존 계획은 BLOCK.tableScan을 사용하며 해당 BLOCK 노드 scanCount가1002였다. 후보에서는 기존 외래 키 인덱스를 사용한다. ROOMMATE_BOARD 스캔과 기타 조인은 남아 있으며 전체 스캔을 없앴다는 의미는 아니다.
- OR을 만족하는 차단 행이 없다는 조건은 두 방향 각각의 차단 행이 없다는 AND 조건과 논리적으로 같다. is_deleted=false 조건을 양쪽에 동일하게 유지했다.
- literal SQL/EXPLAIN 진단이며 실제 API의 바인딩·트랜잭션·HTTP 시간과 범위가 다르다. **95.58~98.55%는 이 SQL 후보 실험의 시간 감소이며 API 성능 개선률이 아니다.** 공유 호스트 변동도 있다.
- 소스 반영 후 익명/인증, 양방향/삭제 차단, likedOnly, 빈/많은 검색 결과, 필터·페이지·정렬 계약을 검증하고 동일 측정기 리비전·같은 snapshot으로 API를 다시 측정해야 한다.

## 다음 구현 위치

`RoommateBoardRepositoryImpl.notBlockedBetween`에서 단일 NOT EXISTS 안의 OR을 방향별 두 NOT EXISTS의 AND로 변경한다. 현재 검색 기록 저장·트랜잭션 계약은 유지한다. 현재 조회는 이미지/인증/관심 정보를 이미 배치로 읽으므로 N+1 제거 작업으로 오인하지 않는다.

- [원본·후보 SQL, 회원별 결과 및10회 실행 통계](./results.json), [정리 확인](./cleanup.json).
- [SQL 진단](../report.md), [실험 도구](../../../../../tools/probe-roommate-board-block-sql.py).
