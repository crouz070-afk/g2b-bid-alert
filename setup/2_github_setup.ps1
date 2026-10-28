# 나라장터 알림 - GitHub 리포지토리 생성 + 시크릿 등록 + Pages 설정
#
# 실행:  PowerShell에서
#   cd "$env:USERPROFILE\OneDrive\바탕 화면\작업결과물\g2b-bid-alert"
#   powershell -ExecutionPolicy Bypass -File setup\2_github_setup.ps1
#
# 먼저 setup\1_kakao_token.py 로 setup\.env 를 만들어 둔다.
# 사람이 할 일은 GitHub 로그인 창에서 코드 붙여넣기 한 번뿐이다.

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT
$REPO = "g2b-bid-alert"

# ---------- 1. gh CLI ----------
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    winget install --id GitHub.cli --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
}

# ---------- 2. 로그인 ----------
gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { gh auth login --hostname github.com --git-protocol https --web --scopes "repo,workflow" }
gh auth setup-git
$USER = (gh api user --jq .login)
$PAGES = "https://$USER.github.io/$REPO/"

# ---------- 3. 기존 로컬 상태 이관 + 페이지 주소 기록 ----------
python -X utf8 setup\0_import_local_state.py
python -X utf8 -c "import json;p='config.json';c=json.load(open(p,encoding='utf-8'));c['pages_url']='$PAGES';json.dump(c,open(p,'w',encoding='utf-8',newline='\n'),ensure_ascii=False,indent=2)"
git add -A
git commit -q -m "로컬 이력·상태 이관, 페이지 주소 설정"

# ---------- 4. 공개 리포지토리 생성 + 푸시 ----------
# 공개여야 무료 GitHub Pages가 열린다. 공고 정보는 원래 공개 정보이고 키는 시크릿에만 둔다.
gh repo view "$USER/$REPO" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    gh repo create $REPO --public --source=. --remote=origin --push
} else {
    git remote get-url origin 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { git remote add origin "https://github.com/$USER/$REPO.git" }
    git push -u origin main
}

# ---------- 5. 시크릿 ----------
$svcKey = (Get-Content (Join-Path (Split-Path -Parent $ROOT) "나라장터_공고알림\config.json") -Raw -Encoding UTF8 | ConvertFrom-Json).serviceKey
$svcKey | gh secret set G2B_SERVICE_KEY --repo "$USER/$REPO"

$kv = @{}
foreach ($ln in Get-Content (Join-Path $PSScriptRoot ".env") -Encoding UTF8) {
    if ($ln -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $kv[$Matches[1]] = $Matches[2].Trim() }
}
foreach ($name in @("KAKAO_REST_KEY","KAKAO_REFRESH_TOKEN","KAKAO_CLIENT_SECRET")) {
    if ($kv[$name]) { $kv[$name] | gh secret set $name --repo "$USER/$REPO" }
}
# 리프레시 토큰 갱신본 암호화 키(로컬에는 남기지 않는다). 다시 만들면 갱신본을 못 풀므로 최초 1회만.
if (-not ((gh secret list --repo "$USER/$REPO") -match "KAKAO_TOKEN_KEY")) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    [Convert]::ToBase64String($bytes) | gh secret set KAKAO_TOKEN_KEY --repo "$USER/$REPO"
}

# ---------- 6. Pages(워크플로 배포) + 첫 실행 ----------
gh api -X POST "repos/$USER/$REPO/pages" -f build_type=workflow 2>$null | Out-Null
gh workflow run scan.yml --repo "$USER/$REPO"

Write-Host ""
Write-Host "완료. 전체 현황: $PAGES"
Write-Host "실행 기록:   https://github.com/$USER/$REPO/actions"
