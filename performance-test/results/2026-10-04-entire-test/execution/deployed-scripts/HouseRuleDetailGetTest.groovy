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
import org.apache.hc.core5.http.message.BasicHeader
import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl
import org.ngrinder.http.HTTPResponse

@RunWith(GrinderRunner)
class HouseRuleDetailGetTest {
    static GTest test
    static HTTPRequest request
    static String targetHost = "http://host.docker.internal:8080"
    static final List<String> TOKEN_POOL = new File('/tmp/knockin-entire-20261004/tokens.txt').readLines('UTF-8')
    static final List<Long> HOUSE_RULE_ID_POOL = [3L,4L,5L,6L,7L,8L,9L,10L,11L,12L,13L,14L,15L,16L,17L,18L,19L,20L,21L,22L,23L,24L,25L,26L,27L,28L,29L,30L,31L,32L]

    private BufferedWriter samples
    private long sampleIteration = 0
    private String userToken
    private Long houseRuleId

    @BeforeProcess
    static void beforeProcess() {
        HTTPRequestControl.setConnectionTimeout(5000)
        HTTPRequestControl.setSocketTimeout(15000)
        test = new GTest(7102, "GET /roommates/me/house-rule/{id}")
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
        int index = grinder.threadNumber % TOKEN_POOL.size()
        userToken = TOKEN_POOL.get(index)
        houseRuleId = HOUSE_RULE_ID_POOL.get(index % HOUSE_RULE_ID_POOL.size())
    }

    @Test
    void test() {
        List<Header> headers = [
            new BasicHeader("Authorization", "Bearer " + userToken),
            new BasicHeader("Accept", "application/json")
        ]
        String api = "/roommates/me/house-rule/" + houseRuleId
        long startedAt = System.currentTimeMillis()
        long startedNs = System.nanoTime()
        HTTPResponse response
        try {
            response = request.GET(targetHost + api, [], headers)
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

    private void writeSample(long startedAt, double elapsedMs, int status, boolean success, String failure) {
        samples.write("${++sampleIteration},${startedAt},${elapsedMs},${status},${success},${failure}\n")
    }
    @AfterThread
    void closeSamples() { samples?.close() }
}
