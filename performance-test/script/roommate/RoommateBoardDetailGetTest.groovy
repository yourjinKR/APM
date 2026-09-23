import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.is
import static org.junit.Assert.assertThat

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import org.junit.Test
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.message.BasicHeader
import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse

@RunWith(GrinderRunner)
class RoommateBoardDetailGetTest {
    static GTest test
    static HTTPRequest request
    static String targetHost = "http://host.docker.internal:8080"
    static final List<String> TOKEN_POOL = ["TOKEN_USER_1", "TOKEN_USER_2", "TOKEN_USER_3"]
    static final List<Long> BOARD_ID_POOL = [1L, 2L, 3L]

    private String userToken
    private Long boardId

    @BeforeProcess
    static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setSocketTimeout(15000)
        test = new GTest(4102, "GET /roommate/boards/{boardId}")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    void beforeThread() {
        grinder.statistics.delayReports = true
        int index = grinder.threadNumber % TOKEN_POOL.size()
        userToken = TOKEN_POOL.get(index)
        boardId = BOARD_ID_POOL.get(index % BOARD_ID_POOL.size())
    }

    @Test
    void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken),
            new BasicHeader("Accept", "application/json")
        ]
        String api = "/roommate/boards/" + boardId
        HTTPResponse response = request.GET(targetHost + api, [], headers)
        assertOk(response, "GET " + api)
    }

    private static void assertOk(HTTPResponse response, String api) {
        if (response.statusCode != 200) {
            grinder.logger.error("{} failed. status={}, body={}", api, response.statusCode, response.bodyText)
            grinder.statistics.forLastTest.success = false
            return
        }
        assertThat(response.statusCode, is(200))
    }
}
