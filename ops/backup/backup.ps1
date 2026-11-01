# Weekly off-GitHub backup of realbtr/firstagi.
# Copies: full git history (bundle), Issues/PRs/Discussions with comments (JSON),
# Release assets, owner's source documents. Never copies .secrets/.
# Integrity: records main's SHA and checks that the previous backup's SHA is
# still an ancestor of main; a rewritten history is reported loudly.
#
#   pwsh -NoProfile -ExecutionPolicy Bypass -File ops\backup\backup.ps1
#   ... -Dest D:\other -Keep 8
param(
    [string]$Repo = "realbtr/firstagi",
    [string[]]$Dest = @("C:\FirstAGI_backups", (Join-Path $env:USERPROFILE "OneDrive\FirstAGI_backups")),
    [int]$Keep = 8,
    [string[]]$ExtraFiles = @((Join-Path $env:USERPROFILE "Documents\Инженерная абхидхарма.docx"))
)
$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$work = Join-Path $env:TEMP "firstagi-backup-$stamp"
New-Item -ItemType Directory -Force $work | Out-Null
$log = New-Object System.Collections.Generic.List[string]
function Note($s) { $log.Add($s); Write-Host $s }

# 1. Full history from GitHub (not the local clone), as a single-file bundle.
$mirror = Join-Path $work "mirror.git"
git clone --mirror --quiet "https://github.com/$Repo.git" $mirror
if ($LASTEXITCODE) { throw "git clone --mirror failed" }
git -C $mirror bundle create (Join-Path $work "firstagi.bundle") --all 2>$null
if ($LASTEXITCODE) { throw "git bundle failed" }
$wiki = Join-Path $work "wiki.git"
git clone --mirror --quiet "https://github.com/$Repo.wiki.git" $wiki
if ($LASTEXITCODE) { Note "!!! wiki clone failed" }
else { git -C $wiki bundle create (Join-Path $work "firstagi-wiki.bundle") --all 2>$null; Remove-Item -Recurse -Force $wiki }
$head = (git -C $mirror rev-parse refs/heads/main).Trim()
Note "main $head"

# 2. Integrity: previous backup's main must still be an ancestor of current main.
$shaLog = Join-Path $Dest[0] "main-sha.log"
if (Test-Path $shaLog) {
    $prev = ((Get-Content $shaLog | Select-Object -Last 1) -split "\s+")[1]
    git -C $mirror merge-base --is-ancestor $prev $head 2>$null
    if ($LASTEXITCODE) { Note "!!! HISTORY REWRITTEN: previous main $prev is not an ancestor of $head" ; $rewritten = $true }
    else { Note "integrity ok: $prev is an ancestor" }
}

# 3. GitHub-only state: issues, PRs, comments, discussions, releases.
$meta = Join-Path $work "github"
New-Item -ItemType Directory -Force $meta | Out-Null
$endpoints = @{
    "issues.json"          = "repos/$Repo/issues?state=all&per_page=100"
    "issue_comments.json"  = "repos/$Repo/issues/comments?per_page=100"
    "pulls.json"           = "repos/$Repo/pulls?state=all&per_page=100"
    "review_comments.json" = "repos/$Repo/pulls/comments?per_page=100"
    "releases.json"        = "repos/$Repo/releases?per_page=100"
    "labels.json"          = "repos/$Repo/labels?per_page=100"
}
foreach ($name in $endpoints.Keys) {
    gh api --paginate --slurp $endpoints[$name] | Set-Content -Encoding utf8 (Join-Path $meta $name)
    if ($LASTEXITCODE) { throw "gh api $name failed" }
}
$owner, $nameOnly = $Repo -split "/"
$q = 'query($o:String!,$n:String!,$c:String){repository(owner:$o,name:$n){discussions(first:20,after:$c){pageInfo{hasNextPage endCursor} nodes{number title url createdAt author{login} category{name} body comments(first:50){nodes{author{login} createdAt body replies(first:20){nodes{author{login} createdAt body}}}}}}}}'
$all = @(); $cursor = $null
do {
    $args_ = @("api", "graphql", "-f", "query=$q", "-F", "o=$owner", "-F", "n=$nameOnly")
    if ($cursor) { $args_ += @("-F", "c=$cursor") }
    $raw = & gh @args_
    if ($LASTEXITCODE) { throw "discussions export failed" }
    $page = ($raw | ConvertFrom-Json).data.repository.discussions
    $all += $page.nodes; $cursor = $page.pageInfo.endCursor
} while ($page.pageInfo.hasNextPage)
$all | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 (Join-Path $meta "discussions.json")
Note "discussions $($all.Count)"

$assets = Join-Path $work "release-assets"
New-Item -ItemType Directory -Force $assets | Out-Null
foreach ($tag in (gh release list -R $Repo --json tagName --jq ".[].tagName")) {
    gh release download $tag -R $Repo -D (Join-Path $assets $tag) --skip-existing
}

# 4. Owner's source documents that live outside the repository.
$docs = Join-Path $work "owner-docs"
New-Item -ItemType Directory -Force $docs | Out-Null
foreach ($f in $ExtraFiles) { if (Test-Path -LiteralPath $f) { Copy-Item -LiteralPath $f $docs } else { Note "missing extra file: $f" } }

# 5. Pack, hash, distribute, rotate.
Remove-Item -Recurse -Force $mirror
$zip = Join-Path $env:TEMP "firstagi-backup-$stamp.zip"
Compress-Archive -Path (Join-Path $work "*") -DestinationPath $zip -Force
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
Note "archive sha256 $hash"
foreach ($d in $Dest) {
    try {
        New-Item -ItemType Directory -Force $d | Out-Null
        Copy-Item $zip $d
        Get-ChildItem $d -Filter "firstagi-backup-*.zip" | Sort-Object Name -Descending |
            Select-Object -Skip $Keep | Remove-Item -Force
        Note "copied to $d"
    } catch { Note "!!! copy to $d failed: $($_.Exception.Message)" }
}
Add-Content -Encoding utf8 $shaLog "$stamp $head $hash"
$log | Set-Content -Encoding utf8 (Join-Path $Dest[0] "last-run.txt")
Remove-Item -Recurse -Force $work, $zip
if ($rewritten) { exit 2 }
