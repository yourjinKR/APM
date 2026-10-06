import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import org.ngrinder.http.HTTPResponse
import org.apache.hc.core5.http.Message
import org.apache.hc.core5.http.message.BasicHttpResponse

// Actual Agent libraries; offline only. The fixture configuration is restored after the checks.
def support = new GroovyClassLoader().parseClass(new File('resources/RoommateBoardListSupport.txt'))
def contract = new GroovyClassLoader().parseClass(new File('resources/RoommateBoardPageContract.txt'))
def loader = new GroovyClassLoader()
loader.parseClass(new File('RoommateBoardListGetTest.groovy'))
loader.parseClass(new File('RoommateBoardListKeywordGetTest.groovy'))
def reject = { Closure action ->
    boolean rejected = false
    try { action() } catch (IllegalArgumentException ignored) { rejected = true }
    assert rejected
}
def validInput = [query: [page: 0, size: 20, sort: 'createdAt,DESC'], expect: [minTotalElements: 1]]
def row = [id: 2, title: '부하 테스트 게시글 999', regionFullName: '서울 강남', roomTypes: ['원룸'],
           gender: 'MALE', deposit: 500, monthlyRent: 40, interested: true, hits: 4,
           createdAt: '2026-09-30T12:00:00']
def body = [status: 200, error: null, data: [number: 0, size: 20, totalElements: 1, content: [row]]]
def slice = body + [data: body.data.findAll { key, value -> key != 'totalElements' }]
contract.validateInput(validInput)
contract.validateBody(body, validInput)
reject { contract.validateInput(validInput.findAll { key, value -> key != 'expect' }) }
reject { contract.validateBody(slice, validInput) }
reject { contract.validateBody(body + [status: 500], validInput) }
reject { contract.validateBody(body + [data: body.data + [content: []]], validInput) }
reject { contract.validateBody(body, validInput + [query: validInput.query + [gender: 'FEMALE']]) }
reject { contract.validateBody(body, validInput + [query: validInput.query + [minMounthRent: 50]]) }
reject { contract.validateBody(body, validInput + [keyword: '판교']) }
reject { contract.validateBody(body + [data: body.data + [content: [row, row]]], validInput) }
reject { contract.validateBody(body + [data: body.data + [content: [row + [id: 1], row], totalElements: 2]], validInput) }
def zero = validInput + [keyword: '없는 검색어', expect: [minTotalElements: 0, totalElements: 0]]
contract.validateBody(body + [data: body.data + [content: [], totalElements: 0]], zero)
def combined = validInput + [keyword: '부하 테스트', query: validInput.query +
        [regionIds: [1, 2], roomTypeIds: [3], gender: 'MALE', minDeposit: 300,
         maxDeposit: 600, minMounthRent: 30, maxMounthRent: 50, likedOnly: true],
        expect: [minTotalElements: 1, regionFragments: ['서울'], roomTypeNames: ['원룸']]]
contract.validateBody(body, combined)

def settings = [profileId: 'smoke', profile: [auth: 'authenticated', inputs: [combined]],
        runId: 'offline-smoke', baseUrl: 'http://unused.invalid', connectTimeoutMs: 5000,
        socketTimeoutMs: 5000, outputDir: args[0], keywordMode: true, expectedStatusCodes: [200],
        responseValidator: null, validatorType: null, configSha256: 'offline-test',
        tokens: ['fake0', 'fake1', 'fake2', 'fake3']]
def context = [agentNumber: 1, processNumber: 11, firstProcessNumber: 10, threadNumber: 0,
        properties: [getInt: { String key, int fallback -> key == 'grinder.processes' ? 2 : 1 }],
        statistics: [forLastTest: [success: true]]]
def responseOf = { int code, String text -> HTTPResponse.of(new Message(new BasicHttpResponse(code), text.getBytes('UTF-8'))) }
def requestOf = { response -> [GET: { String url, List params, List headers -> response }] }
def worker = support.newInstance(settings, context)
assert worker.userSlot == 3
assert worker.headers.find { it.name == 'Authorization' }.value == 'Bearer fake3'
reject { support.newInstance(settings + [tokens: ['fake0']], context) }
def captured = [:]
worker.execute([GET: { String url, List params, List headers ->
    captured.params = params
    return responseOf(200, JsonOutput.toJson(body))
}])
assert captured.params.findAll { it.name == 'regionIds' }*.value == ['1', '2']
assert captured.params.find { it.name == 'keyword' }.value == '부하 테스트'
assert context.statistics.forLastTest.success
worker.execute(requestOf(responseOf(200, JsonOutput.toJson(slice))))
assert context.statistics.forLastTest.success
worker.execute(requestOf([statusCode: 200, bodyBytes: 'not JSON SECRET'.bytes,
        getBodyText: { charset -> throw new AssertionError('Default mode must not parse the body') }]))
assert context.statistics.forLastTest.success
worker.execute(requestOf(responseOf(200, '{"status":500,"error":"business error"}')))
assert context.statistics.forLastTest.success // HTTP-only scope is deliberate.
worker.execute(requestOf(responseOf(500, 'SECRET')))
assert !context.statistics.forLastTest.success
worker.execute([GET: { String url, List params, List headers -> throw new java.net.SocketTimeoutException('SECRET') }])
assert !context.statistics.forLastTest.success
worker.execute([GET: { String url, List params, List headers ->
    throw new java.util.concurrent.ExecutionException(new java.net.SocketTimeoutException('SECRET'))
}])
worker.execute(requestOf(responseOf(200, 'plain text')))
assert context.statistics.forLastTest.success // Failure cannot carry over into a later success.
worker.close()
def csv = new File(args[0], 'offline-smoke/a1-p1-t0.csv').text
assert csv.readLines().size() == 9
assert csv.contains('http_500') && csv.contains('ExecutionException,SocketTimeoutException')
assert !csv.contains('SECRET') && !csv.contains('fake3')
assert !new File(args[0], 'offline-smoke/a1-p1-manifest.json').text.contains('fake3')

def accepted = support.newInstance(settings + [runId: 'offline-accepted', expectedStatusCodes: [201]], context)
accepted.execute(requestOf(responseOf(201, 'created')))
assert context.statistics.forLastTest.success
accepted.close()
def checked = support.newInstance(settings + [runId: 'offline-contract', validationMode: true,
        responseValidator: 'resources/RoommateBoardPageContract.txt', validatorType: contract], context)
checked.execute(requestOf(responseOf(200, JsonOutput.toJson(body))))
assert context.statistics.forLastTest.success
try {
    checked.execute(requestOf(responseOf(200, JsonOutput.toJson(slice))))
    assert false
} catch (IllegalArgumentException failure) {
    assert failure.message.contains('CONTRACT_MISMATCH: contract_mismatch/PAGE_TOTAL_ELEMENTS_REQUIRED (HTTP 200)')
}
reject { checked.execute(requestOf(responseOf(200, 'SECRET malformed JSON'))) }
checked.close()
def contractCsv = new File(args[0], 'offline-contract/a1-p1-t0.csv').text
assert contractCsv.contains('contract_mismatch,PAGE_TOTAL_ELEMENTS_REQUIRED')
assert !contractCsv.contains('SECRET')
def manifest = new JsonSlurper().parse(new File(args[0], 'offline-contract/a1-p1-manifest.json'))
assert manifest.responseValidator == 'resources/RoommateBoardPageContract.txt'
assert !manifest.containsKey('validatorType') && !manifest.containsKey('tokens')
def validationWorker = support.newInstance(settings + [runId: 'offline-validation', validationMode: true], context)
try {
    validationWorker.execute(requestOf(responseOf(401, 'SECRET')))
    assert false
} catch (IllegalArgumentException failure) { assert failure.message.contains('HTTP_REQUEST_FAILED: http_401') }
try {
    validationWorker.execute([GET: { String url, List params, List headers -> throw new java.net.SocketTimeoutException('SECRET') }])
    assert false
} catch (IllegalArgumentException failure) { assert failure.message.contains('TRANSPORT_FAILED: SocketTimeoutException') }
validationWorker.close()

def configFile = new File('resources/roommate-board-list.json')
String original = configFile.text
try {
    assert support.loadSettings(false).profileId == 'list-anonymous'
    assert support.loadSettings(true).profileId == 'search-frequent-authenticated'
    def config = new JsonSlurper().parseText(original)
    config.responseValidator = null
    config.profiles['list-anonymous'].inputs.each { it.remove('expect') }
    configFile.setText(JsonOutput.toJson(config), 'UTF-8')
    assert support.loadSettings(false).validatorType == null
    config.responseValidator = 'resources/RoommateBoardPageContract.txt'
    configFile.setText(JsonOutput.toJson(config), 'UTF-8')
    reject { support.loadSettings(false) }
    config.profiles['list-anonymous'].responseValidator = null
    configFile.setText(JsonOutput.toJson(config), 'UTF-8')
    assert support.loadSettings(false).validatorType == null // Per-profile null overrides global opt-in.
    assert support.loadSettings(true).validatorType != null
    config.expectedStatusCodes = [200, 201]
    config.profiles['list-anonymous'].expectedStatusCodes = [204]
    configFile.setText(JsonOutput.toJson(config), 'UTF-8')
    assert support.loadSettings(false).expectedStatusCodes == [204]
    assert support.loadSettings(true).expectedStatusCodes == [200, 201]
    config.profiles['list-anonymous'].expectedStatusCodes = [200, 200]
    configFile.setText(JsonOutput.toJson(config), 'UTF-8')
    reject { support.loadSettings(false) }
} finally { configFile.setText(original, 'UTF-8') }
def testProperties = new Properties()
testProperties.setProperty('grinder.test.id', 'test_123')
assert support.loadSettings(false, [properties: testProperties]).runId == 'offline-smoke-test_123'
reject { support.loadSettings(false, [properties: new Properties()]) }
testProperties.setProperty('grinder.test.id', '../unsafe')
reject { support.loadSettings(false, [properties: testProperties]) }
def validationProperties = new Properties()
validationProperties.setProperty('grinder.script.validation', 'true')
def firstValidation = support.loadSettings(false, [properties: validationProperties])
def nextValidation = support.loadSettings(false, [properties: validationProperties])
assert firstValidation.validationMode
assert firstValidation.runId ==~ /offline-smoke-validation-[a-f0-9-]+/
assert firstValidation.runId != nextValidation.runId
println 'PASS: HTTP-only Page/Slice/non-JSON, optional Page contract, status/transport errors, configuration overrides, sharding, safe samples and UI validation'
