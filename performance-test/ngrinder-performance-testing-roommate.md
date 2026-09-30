좋아. 이번엔 **`roommate/` 전체 13개 nGrinder Groovy 스크립트 전문**이야.

대상 API:

```plain text
roommate/
├── RoommateBoardListGetTest.groovy
├── RoommateBoardDetailGetTest.groovy
├── RoommateBoardLikePostTest.groovy
├── RoommateBoardEditFormGetTest.groovy
├── RoommateBoardCreateMultipartTest.groovy
├── RoommateBoardUpdateMultipartTest.groovy
├── RoommateBoardReportPostTest.groovy
├── RoommateBoardDeleteTest.groovy
├── RoommateMatchListGetTest.groovy
├── RoommateMatchDetailGetTest.groovy
├── RoommateMatchScoreGetTest.groovy
├── RoommateMatchLikePostTest.groovy
└── RoommateMatchReportPostTest.groovy
```


---

# 게시글 목록·검색의 현재 관리 위치

게시글 목록과 검색의 실행 코드는 [RoommateBoardListGetTest.groovy](./script/roommate/RoommateBoardListGetTest.groovy), [RoommateBoardListKeywordGetTest.groovy](./script/roommate/RoommateBoardListKeywordGetTest.groovy)에서 관리한다. 설정과 실행 절차는 [측정 가이드](./docs/roommate-board-list-testing.md)를 따른다. 목록 코드의 중복 전문은 이 문서에서 제거했다.

아래 나머지 코드는 초기 설계 참고 자료다. 현재 실행 파일과 검증 상태는 [스크립트 인덱스](./script/README.md)를 기준으로 확인한다.

---

# `roommate/RoommateBoardDetailGetTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.message.BasicHeader

import java.util.Random

@RunWith(GrinderRunner)
class RoommateBoardDetailGetTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static int minBoardId = 1
    public static int maxBoardId = 10000

    public static final List<String> TOKEN_POOL = [
        "TOKEN_USER_1",
        "TOKEN_USER_2",
        "TOKEN_USER_3"
    ]

    private Random random = new Random()
    private String userToken
    private Long boardId

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(15000)

        test = new GTest(4002, "GET /roommate/boards/{boardId}")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Before
    public void before() {
        boardId = minBoardId + random.nextInt(maxBoardId - minBoardId + 1)
    }

    @Test
    public void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken)
        ]

        HTTPResponse response = request.GET(targetHost + "/roommate/boards/" + boardId, [], headers)

        if (response.statusCode != 200) {
            grinder.logger.error("GET /roommate/boards/{} failed. status={}, body={}", boardId, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, is(200))
    }
}
```


---

# `roommate/RoommateBoardLikePostTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.message.BasicHeader

import java.util.Random

@RunWith(GrinderRunner)
class RoommateBoardLikePostTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static boolean fixedTarget = true
    public static Long fixedBoardId = 1L

    public static int minBoardId = 1
    public static int maxBoardId = 10000

    public static final List<String> TOKEN_POOL = [
        "TOKEN_USER_1",
        "TOKEN_USER_2",
        "TOKEN_USER_3",
        "TOKEN_USER_4",
        "TOKEN_USER_5",
        "TOKEN_USER_6",
        "TOKEN_USER_7",
        "TOKEN_USER_8",
        "TOKEN_USER_9",
        "TOKEN_USER_10"
    ]

    private Random random = new Random()
    private String userToken
    private Long boardId

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(15000)

        test = new GTest(4003, "POST /roommate/boards/{boardId}/likes")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Before
    public void before() {
        if (fixedTarget) {
            boardId = fixedBoardId
        } else {
            boardId = minBoardId + random.nextInt(maxBoardId - minBoardId + 1)
        }
    }

    @Test
    public void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken),
            new BasicHeader("Content-Type", "application/json")
        ]

        HTTPResponse response = request.POST(
            targetHost + "/roommate/boards/" + boardId + "/likes",
            "".getBytes("UTF-8"),
            headers
        )

        if (!(response.statusCode in [200, 201, 204, 400, 409])) {
            grinder.logger.error("POST /roommate/boards/{}/likes failed. status={}, body={}", boardId, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, anyOf(is(200), is(201), is(204), is(400), is(409)))
    }
}
```


---

# `roommate/RoommateBoardEditFormGetTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.message.BasicHeader

import java.util.Random

@RunWith(GrinderRunner)
class RoommateBoardEditFormGetTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static int minBoardId = 1
    public static int maxBoardId = 1000

    public static final List<String> TOKEN_POOL = [
        "TOKEN_BOARD_OWNER_1",
        "TOKEN_BOARD_OWNER_2",
        "TOKEN_BOARD_OWNER_3"
    ]

    private Random random = new Random()
    private String userToken
    private Long boardId

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(10000)

        test = new GTest(4004, "GET /roommate/boards/{boardId}/edit")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Before
    public void before() {
        boardId = minBoardId + random.nextInt(maxBoardId - minBoardId + 1)
    }

    @Test
    public void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken)
        ]

        HTTPResponse response = request.GET(targetHost + "/roommate/boards/" + boardId + "/edit", [], headers)

        if (!(response.statusCode in [200, 403, 404])) {
            grinder.logger.error("GET /roommate/boards/{}/edit failed. status={}, body={}", boardId, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, anyOf(is(200), is(403), is(404)))
    }
}
```


---

# `roommate/RoommateBoardCreateMultipartTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.ngrinder.http.multipart.MultipartEntityBuilder
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.ContentType
import org.apache.hc.core5.http.message.BasicHeader

import java.io.File
import java.util.Random

@RunWith(GrinderRunner)
class RoommateBoardCreateMultipartTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static String imagePath = "/tmp/ngrinder/room-500kb.jpg"

    public static final List<String> TOKEN_POOL = [
        "TOKEN_USER_1",
        "TOKEN_USER_2",
        "TOKEN_USER_3"
    ]

    private Random random = new Random()
    private String userToken
    private String requestJson

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(30000)

        test = new GTest(4005, "POST /roommate/boards multipart")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Before
    public void before() {
        int suffix = random.nextInt(1000000)

        requestJson = """
        {
          "title": "nGrinder 게시글 ${suffix}",
          "content": "nGrinder performance test board content",
          "regionId": 1,
          "roomTypeId": 1,
          "roomAddOptionIds": [1, 2],
          "deposit": 500,
          "monthlyRent": 50,
          "maintenanceFee": 10
        }
        """
    }

    @Test
    public void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken)
        ]

        def builder = MultipartEntityBuilder.create()
        builder.addTextBody("request", requestJson, ContentType.APPLICATION_JSON)

        File image = new File(imagePath)
        if (image.exists()) {
            builder.addBinaryBody("files", image, ContentType.IMAGE_JPEG, image.getName())
        }

        def entity = builder.build()

        HTTPResponse response = request.POST(targetHost + "/roommate/boards", entity, headers)

        if (!(response.statusCode in [200, 201, 400])) {
            grinder.logger.error("POST /roommate/boards multipart failed. status={}, body={}", response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, anyOf(is(200), is(201), is(400)))
    }
}
```


---

# `roommate/RoommateBoardUpdateMultipartTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.ngrinder.http.multipart.MultipartEntityBuilder
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.ContentType
import org.apache.hc.core5.http.message.BasicHeader

import java.io.File
import java.util.Random

@RunWith(GrinderRunner)
class RoommateBoardUpdateMultipartTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static String imagePath = "/tmp/ngrinder/room-500kb.jpg"

    public static int minBoardId = 1
    public static int maxBoardId = 1000

    public static final List<String> TOKEN_POOL = [
        "TOKEN_BOARD_OWNER_1",
        "TOKEN_BOARD_OWNER_2",
        "TOKEN_BOARD_OWNER_3"
    ]

    private Random random = new Random()
    private String userToken
    private Long boardId
    private String requestJson

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(30000)

        test = new GTest(4006, "PUT /roommate/boards/{boardId} multipart")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Before
    public void before() {
        boardId = minBoardId + random.nextInt(maxBoardId - minBoardId + 1)
        int suffix = random.nextInt(1000000)

        requestJson = """
        {
          "title": "nGrinder 수정 게시글 ${suffix}",
          "content": "nGrinder performance test board update content",
          "regionId": 1,
          "roomTypeId": 1,
          "roomAddOptionIds": [1, 2, 3],
          "deposit": 700,
          "monthlyRent": 60,
          "maintenanceFee": 12
        }
        """
    }

    @Test
    public void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken)
        ]

        def builder = MultipartEntityBuilder.create()
        builder.addTextBody("request", requestJson, ContentType.APPLICATION_JSON)

        File image = new File(imagePath)
        if (image.exists()) {
            builder.addBinaryBody("files", image, ContentType.IMAGE_JPEG, image.getName())
        }

        def entity = builder.build()

        HTTPResponse response = request.PUT(targetHost + "/roommate/boards/" + boardId, entity, headers)

        if (!(response.statusCode in [200, 400, 403, 404])) {
            grinder.logger.error("PUT /roommate/boards/{} multipart failed. status={}, body={}", boardId, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, anyOf(is(200), is(400), is(403), is(404)))
    }
}
```


---

# `roommate/RoommateBoardReportPostTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.message.BasicHeader

import java.util.Random

@RunWith(GrinderRunner)
class RoommateBoardReportPostTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static int minBoardId = 1
    public static int maxBoardId = 10000

    public static final List<String> TOKEN_POOL = [
        "TOKEN_USER_1",
        "TOKEN_USER_2",
        "TOKEN_USER_3"
    ]

    private Random random = new Random()
    private String userToken
    private Long boardId
    private String requestBody

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(10000)

        test = new GTest(4007, "POST /roommate/boards/{boardId}/reports")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Before
    public void before() {
        boardId = minBoardId + random.nextInt(maxBoardId - minBoardId + 1)

        requestBody = """
        {
          "reason": "SPAM",
          "content": "nGrinder report test ${System.currentTimeMillis()}"
        }
        """
    }

    @Test
    public void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken),
            new BasicHeader("Content-Type", "application/json")
        ]

        HTTPResponse response = request.POST(
            targetHost + "/roommate/boards/" + boardId + "/reports",
            requestBody.getBytes("UTF-8"),
            headers
        )

        if (!(response.statusCode in [200, 201, 400, 404, 409])) {
            grinder.logger.error("POST /roommate/boards/{}/reports failed. status={}, body={}", boardId, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, anyOf(is(200), is(201), is(400), is(404), is(409)))
    }
}
```


---

# `roommate/RoommateBoardDeleteTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.message.BasicHeader

import java.util.Random

@RunWith(GrinderRunner)
class RoommateBoardDeleteTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static int minBoardId = 1
    public static int maxBoardId = 100

    public static final List<String> TOKEN_POOL = [
        "TOKEN_BOARD_OWNER_1",
        "TOKEN_BOARD_OWNER_2",
        "TOKEN_BOARD_OWNER_3"
    ]

    private Random random = new Random()
    private String userToken
    private Long boardId

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(10000)

        test = new GTest(4008, "DELETE /roommate/boards/{boardId}")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Before
    public void before() {
        boardId = minBoardId + random.nextInt(maxBoardId - minBoardId + 1)
    }

    @Test
    public void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken)
        ]

        HTTPResponse response = request.DELETE(targetHost + "/roommate/boards/" + boardId, headers)

        if (!(response.statusCode in [200, 204, 403, 404, 409])) {
            grinder.logger.error("DELETE /roommate/boards/{} failed. status={}, body={}", boardId, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, anyOf(is(200), is(204), is(403), is(404), is(409)))
    }
}
```


---

# `roommate/RoommateMatchListGetTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.NameValuePair
import org.apache.hc.core5.http.message.BasicHeader
import org.apache.hc.core5.http.message.BasicNameValuePair

import java.util.Random

@RunWith(GrinderRunner)
class RoommateMatchListGetTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static boolean useAuth = true

    public static final List<String> TOKEN_POOL = [
        "TOKEN_USER_1",
        "TOKEN_USER_2",
        "TOKEN_USER_3"
    ]

    private Random random = new Random()
    private String userToken
    private List<NameValuePair> params

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(20000)

        test = new GTest(4009, "GET /roommate/matches")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        if (useAuth) {
            userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
        }
    }

    @Before
    public void before() {
        params = new ArrayList<>()

        params.add(new BasicNameValuePair("page", String.valueOf(random.nextInt(50))))
        params.add(new BasicNameValuePair("size", "20"))

        if (random.nextInt(100) < 30) {
            params.add(new BasicNameValuePair("regionId", String.valueOf(1 + random.nextInt(10))))
        }

        if (random.nextInt(100) < 20) {
            params.add(new BasicNameValuePair("roomTypeId", String.valueOf(1 + random.nextInt(5))))
        }

        if (useAuth && random.nextInt(100) < 10) {
            params.add(new BasicNameValuePair("likedOnly", "true"))
        }
    }

    @Test
    public void test() {
        List<Header> headers = []

        if (useAuth) {
            headers.add(new BasicHeader("Authorization", "Bearer " + userToken))
        }

        HTTPResponse response = request.GET(targetHost + "/roommate/matches", params, headers)

        if (response.statusCode != 200) {
            grinder.logger.error("GET /roommate/matches failed. status={}, body={}", response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, is(200))
    }
}
```


---

# `roommate/RoommateMatchDetailGetTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.message.BasicHeader

import java.util.Random

@RunWith(GrinderRunner)
class RoommateMatchDetailGetTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static boolean useAuth = true

    public static int minMemberId = 1
    public static int maxMemberId = 10000

    public static final List<String> TOKEN_POOL = [
        "TOKEN_USER_1",
        "TOKEN_USER_2",
        "TOKEN_USER_3"
    ]

    private Random random = new Random()
    private String userToken
    private Long memberId

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(15000)

        test = new GTest(4010, "GET /roommate/matches/{memberId}")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        if (useAuth) {
            userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
        }
    }

    @Before
    public void before() {
        memberId = minMemberId + random.nextInt(maxMemberId - minMemberId + 1)
    }

    @Test
    public void test() {
        List<Header> headers = []

        if (useAuth) {
            headers.add(new BasicHeader("Authorization", "Bearer " + userToken))
        }

        HTTPResponse response = request.GET(targetHost + "/roommate/matches/" + memberId, [], headers)

        if (!(response.statusCode in [200, 404])) {
            grinder.logger.error("GET /roommate/matches/{} failed. status={}, body={}", memberId, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, anyOf(is(200), is(404)))
    }
}
```


---

# `roommate/RoommateMatchScoreGetTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse

@RunWith(GrinderRunner)
class RoommateMatchScoreGetTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(10000)

        test = new GTest(4011, "GET /roommate/matches/score")
        request = new HTTPRequest()
        test.record(request)
    }

    @Test
    public void test() {
        HTTPResponse response = request.GET(targetHost + "/roommate/matches/score")

        if (response.statusCode != 200) {
            grinder.logger.error("GET /roommate/matches/score failed. status={}, body={}", response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, is(200))
    }
}
```


---

# `roommate/RoommateMatchLikePostTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.message.BasicHeader

import java.util.Random

@RunWith(GrinderRunner)
class RoommateMatchLikePostTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static boolean fixedTarget = true
    public static Long fixedMemberId = 2L

    public static int minMemberId = 1
    public static int maxMemberId = 10000

    public static final List<String> TOKEN_POOL = [
        "TOKEN_USER_1",
        "TOKEN_USER_2",
        "TOKEN_USER_3",
        "TOKEN_USER_4",
        "TOKEN_USER_5",
        "TOKEN_USER_6",
        "TOKEN_USER_7",
        "TOKEN_USER_8",
        "TOKEN_USER_9",
        "TOKEN_USER_10"
    ]

    private Random random = new Random()
    private String userToken
    private Long memberId

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(15000)

        test = new GTest(4012, "POST /roommate/matches/{memberId}/likes")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Before
    public void before() {
        if (fixedTarget) {
            memberId = fixedMemberId
        } else {
            memberId = minMemberId + random.nextInt(maxMemberId - minMemberId + 1)
        }
    }

    @Test
    public void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken),
            new BasicHeader("Content-Type", "application/json")
        ]

        HTTPResponse response = request.POST(
            targetHost + "/roommate/matches/" + memberId + "/likes",
            "".getBytes("UTF-8"),
            headers
        )

        if (!(response.statusCode in [200, 201, 204, 400, 404, 409])) {
            grinder.logger.error("POST /roommate/matches/{}/likes failed. status={}, body={}", memberId, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, anyOf(is(200), is(201), is(204), is(400), is(404), is(409)))
    }
}
```


---

# `roommate/RoommateMatchReportPostTest.groovy`

```groovy
import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.*
import static org.junit.Assert.*

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.Before
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.Test

import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.message.BasicHeader

import java.util.Random

@RunWith(GrinderRunner)
class RoommateMatchReportPostTest {

    public static GTest test
    public static HTTPRequest request
    public static String targetHost = "http://host.docker.internal:8080"

    public static int minMemberId = 1
    public static int maxMemberId = 10000

    public static final List<String> TOKEN_POOL = [
        "TOKEN_USER_1",
        "TOKEN_USER_2",
        "TOKEN_USER_3"
    ]

    private Random random = new Random()
    private String userToken
    private Long memberId
    private String requestBody

    @BeforeProcess
    public static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setReadTimeout(10000)

        test = new GTest(4013, "POST /roommate/matches/{memberId}/reports")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    public void beforeThread() {
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Before
    public void before() {
        memberId = minMemberId + random.nextInt(maxMemberId - minMemberId + 1)

        requestBody = """
        {
          "reason": "SPAM",
          "content": "nGrinder member report test ${System.currentTimeMillis()}"
        }
        """
    }

    @Test
    public void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken),
            new BasicHeader("Content-Type", "application/json")
        ]

        HTTPResponse response = request.POST(
            targetHost + "/roommate/matches/" + memberId + "/reports",
            requestBody.getBytes("UTF-8"),
            headers
        )

        if (!(response.statusCode in [200, 201, 400, 404, 409])) {
            grinder.logger.error("POST /roommate/matches/{}/reports failed. status={}, body={}", memberId, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }

        assertThat(response.statusCode, anyOf(is(200), is(201), is(400), is(404), is(409)))
    }
}
```


---

여기까지가 **`roommate/` 13개 전체 스크립트 전문**이야.

다음 묶음은 이거야.

```plain text
chat-request/
├── ChatRequestListGetTest.groovy
├── ChatRequestDetailGetTest.groovy
├── ChatRequestCreatePostTest.groovy
├── ChatRequestAcceptPostTest.groovy
├── ChatRequestRejectPostTest.groovy
└── ChatRequestCancelPostTest.groovy

chat/
├── ChatRoomListGetTest.groovy
├── ChatRoomDetailGetTest.groovy
├── ChatRoomCreatePostTest.groovy
├── ChatRoomLeavePostTest.groovy
├── ChatRoomImageUploadMultipartTest.groovy
└── ChatMessageWebSocketTest.groovy
```


원하면 바로 이어서 **`chat-request/` + `chat/` 12개 전문** 뽑아줄게.