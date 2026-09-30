import groovy.json.JsonOutput
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Message
import org.apache.hc.core5.http.message.BasicHttpResponse

// Run from performance-test/script/roommate. Offline regression harness: actual nGrinder/HTTP classes, no backend calls.
def support = new GroovyClassLoader().parseClass(new File('resources/RoommateBoardListSupport.txt'))
def loader = new GroovyClassLoader()
loader.parseClass(new File('RoommateBoardListGetTest.groovy'))
loader.parseClass(new File('RoommateBoardListKeywordGetTest.groovy'))
def validInput = [query: [page: 0, size: 20, sort: 'createdAt,DESC'], expect: [minTotalElements: 1]]
def row = [id: 2, title: '부하 테스트 게시글 999', regionFullName: '서울 강남', roomTypes: ['원룸'],
           gender: 'MALE', deposit: 500, monthlyRent: 40, interested: true, hits: 4,
           createdAt: '2026-09-30T12:00:00']
def body = [status: 200, error: null, data: [number: 0, size: 20, totalElements: 1, content: [row]]]
support.validateResponse(body, validInput)
def reject = { Closure action ->
    boolean rejected = false
    try { action() } catch (IllegalArgumentException ignored) { rejected = true }
    assert rejected
}
reject { support.validateResponse(body + [status: 500], validInput) }
reject { support.validateResponse(body + [data: body.data + [content: []]], validInput) }
reject { support.validateResponse(body, validInput + [query: validInput.query + [gender: 'FEMALE']]) }
reject { support.validateResponse(body, validInput + [query: validInput.query + [minMounthRent: 50]]) }
reject { support.validateResponse(body, validInput + [keyword: '판교']) }
reject { support.validateResponse(body + [data: body.data + [content: [row, row]]], validInput) }
def zero = validInput + [keyword: '없는 검색어', expect: [minTotalElements: 0, totalElements: 0]]
support.validateResponse(body + [data: body.data + [content: [], totalElements: 0]], zero)
def combined = validInput + [keyword: '부하 테스트', query: validInput.query +
        [regionIds: [1, 2], roomTypeIds: [3], gender: 'MALE', minDeposit: 300,
         maxDeposit: 600, minMounthRent: 30, maxMounthRent: 50, likedOnly: true],
        expect: [minTotalElements: 1, regionFragments: ['서울'], roomTypeNames: ['원룸']]]
support.validateResponse(body, combined)
def settings = [profileId: 'smoke', profile: [auth: 'authenticated', inputs: [combined]],
        runId: 'offline-smoke', baseUrl: 'http://unused.invalid', connectTimeoutMs: 5000,
        socketTimeoutMs: 5000, outputDir: args[0], keywordMode: true,
        configSha256: 'offline-test', tokens: ['fake0', 'fake1', 'fake2', 'fake3']]
def context = [agentNumber: 1, processNumber: 11, firstProcessNumber: 10, threadNumber: 0,
        properties: [getInt: { String key, int fallback -> key == 'grinder.processes' ? 2 : 1 }],
        statistics: [forLastTest: [success: true]]]
def worker = support.newInstance(settings, context)
assert worker.userSlot == 3
assert worker.headers.find { it.name == 'Authorization' }.value == 'Bearer fake3'
reject { support.newInstance(settings + [tokens: ['fake0']], context) }
def captured = [:]
def response = HTTPResponse.of(new Message(new BasicHttpResponse(200), JsonOutput.toJson(body).getBytes('UTF-8')))
worker.execute([GET: { String url, List params, List headers ->
    captured.url = url; captured.params = params
    return response
}])
assert captured.params.findAll { it.name == 'regionIds' }*.value == ['1', '2']
assert captured.params.find { it.name == 'keyword' }.value == '부하 테스트'
assert context.statistics.forLastTest.success
worker.execute([GET: { String url, List params, List headers -> throw new java.net.SocketTimeoutException('SECRET') }])
assert !context.statistics.forLastTest.success
worker.close()
def csv = new File(args[0], 'offline-smoke/a1-p1-t0.csv').text
assert csv.readLines().size() == 3
assert csv.contains('SocketTimeoutException') && !csv.contains('SECRET') && !csv.contains('fake3')
assert !new File(args[0], 'offline-smoke/a1-p1-manifest.json').text.contains('fake3')
assert support.loadSettings(false).profileId == 'list-anonymous'
assert support.loadSettings(true).profileId == 'search-frequent-authenticated'
def testProperties = new Properties()
testProperties.setProperty('grinder.test.id', 'test_123')
assert support.loadSettings(false, [properties: testProperties]).runId == 'offline-smoke-test_123'
println 'Offline compilation, filters, response validation, sharding, samples and timeout checks passed'
