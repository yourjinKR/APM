<#
.SYNOPSIS
Runs the 14 previously validated nGrinder read scripts with one VUser, one test at a time.

.EXAMPLE
$env:NGRINDER_PASSWORD = '<controller password>'
./run-read-sequential.ps1 -BackendProject C:/dev/workspace/KnockIn/back/11th-1team-BE -SeedSizes 500,1000 -Repetitions 3 -IterationsPerRun 10

.EXAMPLE
./run-read-sequential.ps1 -SeedSizes 1000 -JarPath 'C:/path/to/KnockIn.jar'

.NOTES
With -SeedSizes, pass -BackendProject to build, or -JarPath to use a built jar. It
starts one H2 server per seed, and stops only the server process it started.
Without -SeedSizes, it uses the already running backend and records seedSize=-1.
The Groovy scripts currently target host.docker.internal:8080.
#>
param(
    [int[]] $SeedSizes = @(),
    [ValidateRange(1, 1000)] [int] $Repetitions = 1,
    [ValidateRange(1, 100000)] [int] $IterationsPerRun = 1,
    [string[]] $OnlyScripts = @(),
    [string] $ControllerUrl = 'http://localhost',
    [string] $BackendUrl = 'http://localhost:8080',
    [string] $Username = 'admin',
    [string] $Password = $env:NGRINDER_PASSWORD,
    [string] $JavaPath = '',
    [string] $JarPath = '',
    [string] $BackendProject = '',
    [string] $OutputDirectory = (Join-Path $PSScriptRoot ("../results/{0}-read-sequential" -f (Get-Date -Format 'yyyy-MM-dd'))),
    [ValidateRange(30, 7200)] [int] $RunTimeoutSeconds = 600,
    [switch] $ListOnly
)

$ErrorActionPreference = 'Stop'
$ControllerUrl = $ControllerUrl.TrimEnd('/')
$BackendUrl = $BackendUrl.TrimEnd('/')
if ($BackendUrl -ne 'http://localhost:8080') {
    throw 'The registered Groovy scripts target host.docker.internal:8080; backend checks must use http://localhost:8080.'
}
# Backend source location is independent of the APM checkout.
if ($SeedSizes.Count -gt 0 -and !$JarPath -and !$BackendProject) {
    throw 'With -SeedSizes, pass -BackendProject <backend checkout> or -JarPath <built jar>.'
}
if ($BackendProject) { $BackendProject = (Resolve-Path -LiteralPath $BackendProject).Path }
$ScriptNames = @(
    'CalendarCategoryGetTest.groovy',
    'CalendarDayListGetTest.groovy',
    'CalendarEditFormGetTest.groovy',
    'CalendarMonthListGetTest.groovy',
    'ChatRoomListGetTest.groovy',
    'HouseRuleListGetTest.groovy',
    'MyRoommateGetTest.groovy',
    'RoommateBoardDetailGetTest.groovy',
    'RoommateBoardEditFormGetTest.groovy',
    'RoommateBoardListGetTest.groovy',
    'RoommateMatchDetailGetTest.groovy',
    'RoommateMatchListGetTest.groovy',
    'RoommateRequestListGetTest.groovy',
    'UserBoardsGetTest.groovy'
)
if ($OnlyScripts.Count -gt 0) {
    $unknown = @($OnlyScripts | Where-Object { $_ -notin $ScriptNames })
    if ($unknown.Count -gt 0) { throw "Not in the verified read suite: $($unknown -join ', ')" }
    $ScriptNames = @($ScriptNames | Where-Object { $_ -in $OnlyScripts })
}

if ([string]::IsNullOrWhiteSpace($Password)) {
    throw 'Set NGRINDER_PASSWORD or pass -Password before running.'
}
if ($SeedSizes.Count -gt 0 -and ($SeedSizes | Where-Object { $_ -le 0 }).Count -gt 0) {
    throw 'Every seed size must be a positive integer.'
}

$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${Username}:${Password}"))
$headers = @{ Authorization = "Basic $basic" }

function Get-Controller([string] $path) {
    Invoke-RestMethod -Uri "$ControllerUrl$path" -Headers $headers -TimeoutSec 15
}

function Test-BackendHealth {
    try {
        $health = Invoke-RestMethod -Uri "$BackendUrl/actuator/health" -TimeoutSec 5
        return $health.status -eq 'UP'
    } catch {
        return $false
    }
}

function Wait-BackendHealth([int] $timeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-BackendHealth) { return }
        Start-Sleep -Seconds 2
    }
    throw "Backend did not become healthy within $timeoutSeconds seconds."
}

function Wait-ControllerIdle([int] $timeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = Get-Controller '/perftest/api/status'
        if ($status.runningTestsCount -eq 0) { return }
        Start-Sleep -Seconds 2
    }
    throw "nGrinder still has running tests after $timeoutSeconds seconds."
}

function Resolve-BackendJar {
    if ($JarPath) { return (Resolve-Path -LiteralPath $JarPath).Path }
    Write-Host 'Building the backend jar...'
    Push-Location $BackendProject
    try {
        & (Join-Path $BackendProject 'gradlew.bat') bootJar --no-daemon
        if ($LASTEXITCODE -ne 0) { throw 'Gradle bootJar failed.' }
    } finally {
        Pop-Location
    }
    $jar = Get-ChildItem (Join-Path $BackendProject 'build/libs') -Filter '*.jar' -File |
        Where-Object { $_.Name -notlike '*-plain.jar' } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (!$jar) { throw 'bootJar finished but no executable jar was found.' }
    return $jar.FullName
}

function Resolve-JavaExecutable {
    if ($JavaPath) { return (Resolve-Path -LiteralPath $JavaPath).Path }
    if ($env:JAVA_HOME) {
        return (Resolve-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin/java.exe')).Path
    }
    $javaCommand = (Get-Command java -ErrorAction Stop).Source
    $settings = (& $javaCommand -XshowSettings:properties -version 2>&1 | Out-String)
    $match = [regex]::Match($settings, '(?m)^\s*java\.home\s*=\s*(.+?)\s*$')
    if (!$match.Success) { throw 'Cannot resolve java.home. Pass -JavaPath explicitly.' }
    return (Resolve-Path -LiteralPath (Join-Path $match.Groups[1].Value 'bin/java.exe')).Path
}

function Start-SeededBackend([string] $resolvedJar, [int] $seedSize, [string] $logPrefix) {
    if (Test-BackendHealth) {
        throw "Backend is already listening at $BackendUrl. Stop it before using -SeedSizes."
    }
    $java = Resolve-JavaExecutable
    $args = @('-jar', ('"' + $resolvedJar + '"'), "--seed.load-test.records-per-entity=$seedSize", '--spring.jpa.show-sql=false')
    $logDirectory = Join-Path $OutputDirectory 'seed-server-logs'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $logName = Split-Path $logPrefix -Leaf
    $stdout = Join-Path $logDirectory "$logName-seed-$seedSize-server.out.log"
    $stderr = Join-Path $logDirectory "$logName-seed-$seedSize-server.err.log"
    $serverWorkingDirectory = if ($BackendProject) { $BackendProject } else { [IO.Path]::GetDirectoryName($resolvedJar) }
    $process = Start-Process -FilePath $java -ArgumentList $args -WorkingDirectory $serverWorkingDirectory `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    try {
        Wait-BackendHealth 600
        Write-Host "Backend PID: $($process.Id)"
        return $process
    } catch {
        if (!$process.HasExited) { Stop-Process -Id $process.Id -Force }
        throw
    }
}

function Get-BoardCount {
    try {
        $response = Invoke-RestMethod -Uri "$BackendUrl/roommate/boards?page=0&size=1" -TimeoutSec 30
        if ($response.status -ne 200) { return $null }
        return $response.data.totalElements
    } catch {
        return $null
    }
}

function Write-Results([object[]] $rows, [string] $prefix) {
    if ($rows.Count -eq 0) { return }
    $csvPath = "$prefix.csv"
    $jsonPath = "$prefix.json"
    $mdPath = "$prefix.md"
    $rows | Export-Csv -LiteralPath $csvPath -NoTypeInformation -Encoding UTF8
    [pscustomobject]@{
        generatedAt = (Get-Date).ToString('o')
        controllerUrl = $ControllerUrl
        backendUrl = $BackendUrl
        repetitions = $Repetitions
        iterationsPerRun = $IterationsPerRun
        results = $rows
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

    $lines = @(
        '# Sequential read API smoke results',
        '',
        "- Controller: $ControllerUrl",
        "- Backend: $BackendUrl",
        "- VUsers: 1 (one agent, process and thread)",
        "- Repetitions per script: $Repetitions",
        "- Iterations per repetition: $IterationsPerRun",
        '- Managed server runs override `spring.jpa.show-sql=false`.',
        '- Mean time is the nGrinder run mean, not a percentile.',
        '',
        '| Seed | Script | Repeat | Test ID | Tests | Errors | Mean ms | Result |',
        '|---:|---|---:|---:|---:|---:|---:|---|'
    )
    foreach ($row in $rows) {
        $lines += "| $($row.seedSize) | $($row.script) | $($row.repetition) | $($row.testId) | $($row.tests) | $($row.errors) | $($row.meanTestTimeMs) | $($row.result) |"
    }
    $lines += @('', 'A result is PASS only when the test finished, every planned iteration succeeded, and nGrinder reported zero errors.')
    $lines | Set-Content -LiteralPath $mdPath -Encoding UTF8
}

$registered = @(Get-Controller '/script/api' | Where-Object { $_.fileType -eq 'GROOVY_SCRIPT' } | ForEach-Object { $_.fileName })
$missing = @($ScriptNames | Where-Object { $_ -notin $registered })
if ($missing.Count -gt 0) { throw "Scripts missing from nGrinder: $($missing -join ', ')" }
if ($ListOnly) {
    $ScriptNames
    return
}

if (!(Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$prefix = Join-Path $OutputDirectory ("read-sequential-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$rows = [System.Collections.Generic.List[object]]::new()
$resolvedJar = $null
$targets = if ($SeedSizes.Count -gt 0) { @($SeedSizes) } else { @(-1) }

try {
    if ($SeedSizes.Count -gt 0) { $resolvedJar = Resolve-BackendJar }
    foreach ($seed in $targets) {
        $backendProcess = $null
        try {
            if ($seed -ge 0) {
                Write-Host "Starting backend with seed size $seed..."
                $backendProcess = Start-SeededBackend $resolvedJar $seed $prefix
            } else {
                if (!(Test-BackendHealth)) { throw "Backend is not healthy at $BackendUrl." }
            }
            $boardCount = Get-BoardCount
            if ($null -eq $boardCount) { throw 'Could not read the board count from the backend.' }
            if ($seed -ge 0 -and $boardCount -lt $seed) {
                throw "Board count $boardCount is smaller than requested seed size $seed."
            }
            Write-Host "Backend ready; seed=$seed boardTotal=$boardCount"

            foreach ($script in $ScriptNames) {
                for ($repeat = 1; $repeat -le $Repetitions; $repeat++) {
                    if (!(Test-BackendHealth)) { throw 'Backend went down during the suite; stopping.' }
                    Wait-ControllerIdle 300
                    $testName = "read-smoke-$seed-$($script -replace '\.groovy$','')-$repeat-$(Get-Date -Format 'HHmmss')"
                    $body = @{
                        testName = $testName
                        scriptName = $script
                        status = 'READY'
                        threshold = 'R'
                        runCount = "$IterationsPerRun"
                        agentCount = '1'
                        processes = '1'
                        threads = '1'
                        targetHosts = 'host.docker.internal'
                        samplingInterval = '2'
                    }
                    $created = Invoke-RestMethod -Uri "$ControllerUrl/perftest/api" -Method Post `
                        -Headers $headers -Body $body -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 30
                    $deadline = (Get-Date).AddSeconds($RunTimeoutSeconds)
                    $completed = $null
                    while ((Get-Date) -lt $deadline) {
                        Start-Sleep -Seconds 2
                        $state = Get-Controller "/perftest/api/$($created.id)"
                        if ($state.finishTime -and !$state.status.stoppable) { $completed = $state; break }
                    }
                    if (!$completed) { throw "Test $($created.id) did not finish within $RunTimeoutSeconds seconds." }
                    $pass = $completed.status.name -eq 'FINISHED' -and
                        $completed.tests -eq $IterationsPerRun -and $completed.errors -eq 0
                    $row = [pscustomobject]@{
                        seedSize = $seed
                        boardTotal = $boardCount
                        script = $script
                        repetition = $repeat
                        testId = $completed.id
                        status = $completed.status.name
                        tests = $completed.tests
                        errors = $completed.errors
                        meanTestTimeMs = $completed.meanTestTime
                        tps = $completed.tps
                        scriptRevision = $completed.scriptRevision
                        lastProgressMessage = $completed.lastProgressMessage
                        result = if ($pass) { 'PASS' } else { 'FAIL' }
                    }
                    $rows.Add($row)
                    Write-Results $rows.ToArray() $prefix
                    Write-Host "$seed $script repeat=$repeat test=$($row.testId) $($row.result) tests=$($row.tests) errors=$($row.errors) meanMs=$($row.meanTestTimeMs)"
                }
            }
        } finally {
            if ($backendProcess) {
                $ownedPid = $backendProcess.Id
                if (Get-Process -Id $ownedPid -ErrorAction SilentlyContinue) {
                    Stop-Process -Id $ownedPid -Force
                }
                $deadline = (Get-Date).AddSeconds(30)
                while ((Get-Date) -lt $deadline -and (Test-BackendHealth)) {
                    Start-Sleep -Seconds 1
                }
                if (Test-BackendHealth) {
                    throw "Backend is still healthy after stopping owned PID $ownedPid."
                }
            }
        }
    }
} finally {
    Write-Results $rows.ToArray() $prefix
    if ($rows.Count -gt 0) { Write-Host "Results: $prefix.csv, $prefix.json, $prefix.md" }
}
