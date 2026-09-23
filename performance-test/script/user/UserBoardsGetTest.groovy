import static net.grinder.script.Grinder.grinder
import static org.hamcrest.Matchers.is
import static org.junit.Assert.assertThat

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import org.junit.Test
import org.apache.hc.core5.http.Header
import org.apache.hc.core5.http.NameValuePair
import org.apache.hc.core5.http.message.BasicHeader
import org.apache.hc.core5.http.message.BasicNameValuePair
import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse

@RunWith(GrinderRunner)
class UserBoardsGetTest {
    static GTest test
    static HTTPRequest request
    static String targetHost = "http://host.docker.internal:8080"
    static final List<String> TOKEN_POOL = ["TOKEN_USER_1", "TOKEN_USER_2", "TOKEN_USER_3"]

    private String userToken

    @BeforeProcess
    static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setSocketTimeout(15000)
        test = new GTest(3020, "GET /users/me/boards")
        request = new HTTPRequest()
        test.record(request)
    }

    @BeforeThread
    void beforeThread() {
        grinder.statistics.delayReports = true
        userToken = TOKEN_POOL.get(grinder.threadNumber % TOKEN_POOL.size())
    }

    @Test
    void test() {
        List<NameValuePair> params = [
            new BasicNameValuePair("page", "0"),
            new BasicNameValuePair("size", "20"),
            new BasicNameValuePair("sort", "createdAt,DESC")
        ]
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken),
            new BasicHeader("Accept", "application/json")
        ]
        HTTPResponse response = request.GET(targetHost + "/users/me/boards", params, headers)
        assertOk(response, "GET /users/me/boards")
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
