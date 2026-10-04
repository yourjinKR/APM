import groovy.json.JsonSlurper
import java.nio.file.Files
import net.grinder.scriptengine.groovy.junit.annotation.AfterThread
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
    static final List<String> TOKEN_POOL = new File('/tmp/knockin-entire-20261004/tokens.txt').readLines('UTF-8')

    private BufferedWriter samples
    private long sampleIteration = 0
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
        File sampleDir = new File('/tmp/knockin-entire-20261004', grinder.properties.getProperty('grinder.test.id'))
        Files.createDirectories(sampleDir.toPath())
        File sampleFile = new File(sampleDir, "a${grinder.agentNumber}-p${grinder.processNumber}-t${grinder.threadNumber}.csv")
        if (!sampleFile.createNewFile()) throw new IllegalStateException('Duplicate sample file')
        samples = sampleFile.newWriter('UTF-8')
        samples.write('iteration,startedAtEpochMs,elapsedMs,httpStatus,success,failure\n')
        samples.flush()
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
        long startedAt = System.currentTimeMillis()
        long startedNs = System.nanoTime()
        HTTPResponse response
        try {
            response = request.GET(targetHost + "/users/me/boards", params, headers)
        } catch (Exception error) {
            writeSample(startedAt, (System.nanoTime()-startedNs)/1000000d, 0, false, error.class.simpleName)
            throw error
        }
        double elapsedMs = (System.nanoTime()-startedNs)/1000000d
        boolean contractOk = response.statusCode == 200
        if (contractOk) {
            try {
                def json = new JsonSlurper().parseText(response.bodyText)
                contractOk = json.status == 200 && json.data != null
            } catch (Exception ignored) { contractOk = false }
        }
        if (!contractOk) grinder.statistics.forLastTest.success = false
        writeSample(startedAt, elapsedMs, response.statusCode, contractOk, contractOk ? '' : 'HTTP_OR_CONTRACT')
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

    private void writeSample(long startedAt, double elapsedMs, int status, boolean success, String failure) {
        samples.write("${++sampleIteration},${startedAt},${elapsedMs},${status},${success},${failure}\n")
    }
    @AfterThread
    void closeSamples() { samples?.close() }
}
