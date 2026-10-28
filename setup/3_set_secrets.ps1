# 나라장터 알림 - GitHub 시크릿 등록 (값은 화면에 출력하지 않는다)
#
# 실행:  powershell -ExecutionPolicy Bypass -File setup\3_set_secrets.ps1
#
# - G2B_SERVICE_KEY      : 기존 나라장터_공고알림\config.json 의 서비스키
# - KAKAO_*              : setup\.env (1_kakao_token.py 가 만든 파일)
# - KAKAO_TOKEN_KEY      : 리프레시 토큰 갱신본 암호화 키. 이미 있으면 건드리지 않는다.

$ErrorActionPreference = "Stop"
$gh   = "C:\Program Files\GitHub CLI\gh.exe"
$ROOT = Split-Path -Parent $PSScriptRoot
$USER = (& $gh api user --jq .login)
$R    = "$USER/g2b-bid-alert"

$svc = (Get-Content (Join-Path (Split-Path -Parent $ROOT) "나라장터_공고알림\config.json") -Raw -Encoding UTF8 | ConvertFrom-Json).serviceKey
& $gh secret set G2B_SERVICE_KEY --repo $R --body $svc

$kv = @{}
foreach ($ln in Get-Content (Join-Path $PSScriptRoot ".env") -Encoding UTF8) {
    if ($ln -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $kv[$Matches[1]] = $Matches[2].Trim() }
}
foreach ($n in @("KAKAO_REST_KEY","KAKAO_REFRESH_TOKEN","KAKAO_CLIENT_SECRET")) {
    if ($kv[$n]) { & $gh secret set $n --repo $R --body $kv[$n] }
}

if (-not ((& $gh secret list --repo $R) -match "KAKAO_TOKEN_KEY")) {
    $b = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    & $gh secret set KAKAO_TOKEN_KEY --repo $R --body ([Convert]::ToBase64String($b))
}

Write-Host ""
Write-Host "등록된 시크릿:" -ForegroundColor Cyan
& $gh secret list --repo $R
