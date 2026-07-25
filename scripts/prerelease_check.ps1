#Requires -Version 5.1
<#
.SYNOPSIS
  MediaSync115 上线前一键回归：容器就绪 → pytest → API 冒烟 → Playwright UI（可选 --Live）

.EXAMPLE
  .\scripts\prerelease_check.ps1
  .\scripts\prerelease_check.ps1 -Live
  .\scripts\prerelease_check.ps1 -SkipUnit -SkipUi
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = $(if ($env:MEDIASYNC_BASE_URL) { $env:MEDIASYNC_BASE_URL } else { "http://127.0.0.1:5173" }),
    [string]$Username = $(if ($env:MEDIASYNC_USER) { $env:MEDIASYNC_USER } else { "admin" }),
    [string]$Password = $(if ($env:MEDIASYNC_PASSWORD) { $env:MEDIASYNC_PASSWORD } else { "password" }),
    [string]$ContainerName = "mediasync115",
    [switch]$Live,
    [switch]$SkipUnit,
    [switch]$SkipApi,
    [switch]$SkipUi,
    [switch]$Strict,
    [int]$ReadyTimeoutSec = 180
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Failed = @()
$Passed = @()

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Wait-HttpOk([string]$Url, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $last = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                return
            }
            $last = "HTTP $($resp.StatusCode)"
        } catch {
            $last = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }
    throw "等待服务就绪超时: $Url ($last)"
}

function Resolve-PythonCommand {
    foreach ($candidate in @("python", "python3", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            if ($candidate -eq "py") {
                return @{ Exe = $cmd.Source; PrefixArgs = @("-3") }
            }
            return @{ Exe = $cmd.Source; PrefixArgs = @() }
        }
    }
    return $null
}

function Invoke-HostOrDockerPython {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][string[]]$ScriptArgs,
        [string]$WorkDir = $RepoRoot
    )
    $py = Resolve-PythonCommand
    if ($py) {
        Write-Host "使用本机 Python: $($py.Exe)"
        & $py.Exe @($py.PrefixArgs + @($ScriptPath) + $ScriptArgs)
        return $LASTEXITCODE
    }

    $running = docker ps --format "{{.Names}}" 2>$null | Where-Object { $_ -eq $ContainerName }
    if (-not $running) {
        throw "本机无可用 Python，且容器 $ContainerName 未运行，无法执行 $ScriptPath"
    }

    $remote = "/tmp/$(Split-Path $ScriptPath -Leaf)"
    Write-Host "本机无 Python，改用 docker exec $ContainerName"
    docker cp $ScriptPath "${ContainerName}:${remote}"
    docker exec `
        -e "MEDIASYNC_BASE_URL=$BaseUrl" `
        -e "MEDIASYNC_USER=$Username" `
        -e "MEDIASYNC_PASSWORD=$Password" `
        $ContainerName python $remote @ScriptArgs
    return $LASTEXITCODE
}

function Invoke-BackendPytest {
    $backendDir = Join-Path $RepoRoot "backend"
    $image = docker inspect -f "{{.Config.Image}}" $ContainerName 2>$null
    if (-not $image) {
        $image = "mediasync115:latest"
    }

    Write-Host "在临时容器中运行 pytest（镜像: $image）"
    docker run --rm `
        -v "${backendDir}:/work" `
        -w /work `
        -e "DATABASE_URL=sqlite+aiosqlite:///./data/prerelease_unit.db" `
        -e "TMDB_API_KEY=test-api-key" `
        -e "APP_NAME=MediaSync115-Prerelease" `
        --entrypoint "" `
        $image `
        sh -c "pip install -q pytest pytest-asyncio pytest-cov && mkdir -p data && pytest -q --tb=line"
    return $LASTEXITCODE
}

Push-Location $RepoRoot
try {
    Write-Host "MediaSync115 上线前回归"
    Write-Host "仓库: $RepoRoot"
    Write-Host "BaseUrl: $BaseUrl"

    # ── L0 就绪 ──
    Write-Step "L0 等待服务就绪"
    try {
        Wait-HttpOk "$BaseUrl/healthz" $ReadyTimeoutSec
        try {
            Wait-HttpOk "http://127.0.0.1:9008/healthz" 30
        } catch {
            Write-Host "WARN: 9008/healthz 不可达（可忽略若未映射该端口）: $($_.Exception.Message)" -ForegroundColor Yellow
        }
        $Passed += "L0_ready"
    } catch {
        Write-Host "FAIL: $($_.Exception.Message)" -ForegroundColor Red
        $Failed += "L0_ready"
        throw
    }

    # ── L1 单元测试 ──
    if (-not $SkipUnit) {
        Write-Step "L1 后端 pytest"
        $code = Invoke-BackendPytest
        if ($code -ne 0) {
            Write-Host "FAIL: pytest 退出码 $code" -ForegroundColor Red
            $Failed += "L1_pytest"
        } else {
            $Passed += "L1_pytest"
        }
    } else {
        Write-Host "跳过 L1 pytest (-SkipUnit)"
    }

    # ── L2 API 冒烟 ──
    if (-not $SkipApi) {
        Write-Step "L2 API 模块冒烟"
        $apiScript = Join-Path $RepoRoot "scripts\prerelease_api_smoke.py"
        $apiArgs = @(
            "--base-url", $BaseUrl,
            "--username", $Username,
            "--password", $Password
        )
        if ($Strict) { $apiArgs += "--strict" }
        $code = Invoke-HostOrDockerPython -ScriptPath $apiScript -ScriptArgs $apiArgs
        if ($code -ne 0) {
            Write-Host "FAIL: API smoke 退出码 $code" -ForegroundColor Red
            $Failed += "L2_api_smoke"
        } else {
            $Passed += "L2_api_smoke"
        }
    } else {
        Write-Host "跳过 L2 API smoke (-SkipApi)"
    }

    # ── L4 实网副作用（可选）──
    if ($Live) {
        Write-Step "L4 实网转存/订阅队列冒烟 (--Live)"
        $liveScript = Join-Path $RepoRoot "backend\tests\run_live_subscription_transfer_smoke.py"
        $liveArgs = @(
            "--base-url", $BaseUrl,
            "--username", $Username,
            "--password", $Password
        )
        $code = Invoke-HostOrDockerPython -ScriptPath $liveScript -ScriptArgs $liveArgs
        if ($code -ne 0) {
            Write-Host "FAIL: live smoke 退出码 $code" -ForegroundColor Red
            $Failed += "L4_live"
        } else {
            $Passed += "L4_live"
        }
    }

    # ── L3 Playwright UI ──
    if (-not $SkipUi) {
        Write-Step "L3 Playwright UI 冒烟"
        $frontendDir = Join-Path $RepoRoot "frontend"
        if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
            Write-Host "安装前端依赖..."
            Push-Location $frontendDir
            try { npm ci } finally { Pop-Location }
        }
        Push-Location $frontendDir
        try {
            $env:PLAYWRIGHT_FRONTEND_BASE_URL = $BaseUrl
            $env:PLAYWRIGHT_BACKEND_HEALTH_URL = "$BaseUrl/healthz"
            npm run test:smoke
            $code = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        if ($code -ne 0) {
            Write-Host "FAIL: Playwright 退出码 $code" -ForegroundColor Red
            $Failed += "L3_ui_smoke"
        } else {
            $Passed += "L3_ui_smoke"
        }
    } else {
        Write-Host "跳过 L3 UI smoke (-SkipUi)"
    }

    Write-Host ""
    Write-Host "======== 汇总 ========" -ForegroundColor Cyan
    Write-Host ("通过: " + ($Passed -join ", "))
    if ($Failed.Count -gt 0) {
        Write-Host ("失败: " + ($Failed -join ", ")) -ForegroundColor Red
        exit 1
    }
    Write-Host "全部通过，可以上线验证这一轮基础功能。" -ForegroundColor Green
    exit 0
} finally {
    Pop-Location
}
