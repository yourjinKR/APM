import static net.grinder.script.Grinder.grinder

import net.grinder.script.GTest
import net.grinder.scriptengine.groovy.junit.GrinderRunner
import net.grinder.scriptengine.groovy.junit.annotation.BeforeProcess
import net.grinder.scriptengine.groovy.junit.annotation.BeforeThread
import net.grinder.scriptengine.groovy.junit.annotation.AfterThread
import org.junit.Test
import org.junit.runner.RunWith
import org.ngrinder.http.HTTPRequest
import org.ngrinder.http.HTTPRequestControl

/** Upload this script and both resources/ files to the same nGrinder script folder. */
@RunWith(GrinderRunner)
class RoommateBoardListGetTest {
    static Class supportType
    static Map settings
    static HTTPRequest request
    private def worker

    @BeforeProcess
    static void beforeProcess() {
        supportType = new GroovyClassLoader(RoommateBoardListGetTest.class.classLoader)
                .parseClass(new File("resources/RoommateBoardListSupport.txt"))
        settings = supportType.loadSettings(false, grinder)
        HTTPRequestControl.setConnectionTimeout(settings.connectTimeoutMs as int)
        HTTPRequestControl.setSocketTimeout(settings.socketTimeoutMs as int)
        request = new HTTPRequest()
        new GTest(4101, "GET /roommate/boards " + settings.profileId).record(request)
    }

    @BeforeThread
    void beforeThread() {
        grinder.statistics.delayReports = true
        worker = supportType.newInstance(settings, grinder)
    }

    @Test
    void test() { worker.execute(request) }

    @AfterThread
    void afterThread() { worker?.close() }
}
