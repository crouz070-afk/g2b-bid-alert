# 나라장터 알림 - GitHub 리포지토리 생성 + 시크릿 등록 자동화
#
# 실행:  PowerShell에서
#   cd "$env:USERPROFILE\OneDrive\바탕 화면\작업결과물\g2b-bid-alert"
#   powershell -ExecutionPolicy Bypass -File setup\2_깃허브설정.ps1
#
# 사람이 할 일은 중간에 뜨는 GitHub 로그인 창에서 코드 붙여넣기 한 번뿐이다.

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT

Write-Host "=== 나라장터 알림 GitHub 설정 ===" -ForegroundColor Cyan
Write-Host ""

# ---------- 1. gh CLI 확인 / 설치 ----------
$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Host "[1/5] GitHub CLI 설치 중..." -ForegroundColor Yellow
    winget install --id GitHub.cli --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) {
        Write-Host "설치는 됐지만 이 창에서 gh를 못 찾습니다. PowerShell을 새로 열고 다시 실행하세요." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[1/5] GitHub CLI 확인됨" -ForegroundColor Green
}

# ---------- 2. 로그인 ----------
gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[2/5] GitHub 로그인이 필요합니다." -ForegroundColor Yellow
    Write-Host "      화면에 나오는 8자리 코드를 복사하고 Enter를 누르면 브라우저가 열립니다."
    Write-Host "      브라우저에 코드를 붙여넣고 Authorize를 누르세요."
    Write-Host ""
    gh auth login --hostname github.com --git-protocol https --web --scopes "repo,workflow"
    if ($LASTEXITCODE -ne 0) { Write-Host "로그인 실패" -ForegroundColor Red; exit 1 }
} else {
    Write-Host "[2/5] GitHub 로그인 확인됨" -ForegroundColor Green
}

$USER = (gh api user --jq .login)
Write-Host "      계정: $USER"

# ---------- 3. 리포지토리 생성 + 푸시 ----------
$REPO = "g2b-bid-alert"
$exists = $true
gh repo view "$USER/$REPO" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { $exists = $false }

if ($exists) {
    Write-Host "[3/5] 리포지토리가 이미 있습니다: $USER/$REPO" -ForegroundColor Green
    $hasRemote = $true
    git remote get-url origin 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $hasRemote = $false }
    if (-not $hasRemote) { git remote add origin "https://github.com/$USER/$REPO.git" }
    git push -u origin main
} else {
    Write-Host "[3/5] 비공개 리포지토리 생성 후 푸시..." -ForegroundColor Yellow
    gh repo create $REPO --private --source=. --remote=origin --push
}
if ($LASTEXITCODE -ne 0) { Write-Host "푸시 실패" -ForegroundColor Red; exit 1 }

# ---------- 4. 시크릿 등록 ----------
Write-Host "[4/5] 시크릿 등록 중..." -ForegroundColor Yellow

# 4a. 공공데이터포털 서비스키 - 기존 폴더 config.json에서 가져온다
$oldCfg = Join-Path (Split-Path -Parent $ROOT) "나라장터_공고알림\config.json"
$svcKey = $null
if (Test-Path $oldCfg) {
    $svcKey = (Get-Content $oldCfg -Raw -Encoding UTF8 | ConvertFrom-Json).serviceKey
}
if (-not $svcKey) {
    $svcKey = Read-Host "공공데이터포털 서비스키(Decoding 값)"
}
gh secret set G2B_SERVICE_KEY --body "$svcKey" --repo "$USER/$REPO"
Write-Host "      G2B_SERVICE_KEY 등록" -ForegroundColor Green

# 4b. 카카오 - setup\.env 에서 가져온다
$envF = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envF)) {
    Write-Host ""
    Write-Host "      카카오 토큰이 아직 없습니다. 먼저 아래를 실행하세요:" -ForegroundColor Red
    Write-Host "        python setup\1_카카오토큰받기.py"
    Write-Host "      그 다음 이 스크립트를 다시 실행하면 나머지가 이어집니다."
    exit 1
}
$kv = @{}
foreach ($ln in Get-Content $envF -Encoding UTF8) {
    if ($ln -match '^\s*([A-Z_]+)\s*=\s*(.+)$') { $kv[$Matches[1]] = $Matches[2].Trim() }
}
foreach ($name in @("KAKAO_REST_KEY","KAKAO_REFRESH_TOKEN")) {
    if (-not $kv[$name]) { Write-Host "      $name 없음 — 1번 스크립트를 다시 실행하세요." -ForegroundColor Red; exit 1 }
    gh secret set $name --body $kv[$name] --repo "$USER/$REPO"
    Write-Host "      $name 등록" -ForegroundColor Green
}

# ---------- 5. 첫 실행 ----------
Write-Host "[5/5] 워크플로 수동 실행..." -ForegroundColor Yellow
gh workflow run scan.yml --repo "$USER/$REPO"
Start-Sleep -Seconds 8
gh run list --workflow scan.yml --repo "$USER/$REPO" --limit 3

Write-Host ""
Write-Host "=== 완료 ===" -ForegroundColor Cyan
Write-Host "리포지토리: https://github.com/$USER/$REPO"
Write-Host "실행 현황:  https://github.com/$USER/$REPO/actions"
Write-Host ""
Write-Host "이제 매일 08:00 / 18:00 (KST)에 PC와 무관하게 자동 실행됩니다."
Write-Host "진행 상황은 위 Actions 주소에서 볼 수 있습니다."
