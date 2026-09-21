---
name: teamcity-guide
description: TeamCity CLI usage guidance -- two-phase investigation, token efficiency, queue diagnostics, anti-patterns, artifact analysis. Load before any teamcity CLI call.
---

[Goals]Claude=query constructor+result interpreter|teamcity CLI=read-only CI/CD observability|Together=build triage without 60K-line log dumps
[Safety]TEAMCITY_RO tiers:1=block all writes(default,30 infra+15 orchestration)|infra=block infra/admin only(agent,project,pool,pipeline,skill,API writes)|""=allow all|Most teams stay on =1|Teams with build governance(rate-limiter) use =infra
[Auth]stored:~/.config/tc/config.yml|fallback:teamcity auth login --no-input(reads TEAMCITY_URL+TEAMCITY_TOKEN from env)

[Two-Phase Investigation]Same pattern as incident triage--structured endpoints first, never raw log dump
[Phase1:TRIAGE]What failed + where -- start here ALWAYS
teamcity run list --job <job-id> --branch <branch> --limit 5
teamcity run view <build-id> (build metadata+status+trigger info)
teamcity run log <build-id> --failed
teamcity run tests <build-id> --failed
teamcity run changes <build-id> (VCS changes included in the build)
teamcity run diff <failing-id> <passing-id>
[--failed]Single most important flag|Returns ONLY problems + failed test stack traces|~50 lines vs 60K+ raw

[Phase2:TARGETED]Only after Phase 1 identifies what to look for
teamcity run log <build-id> --tail 50
teamcity run download <id> -a "artifacts/cicd/pipelines/golangci-lint-report.json" -o /tmp/tc-lint
teamcity run log <id> --raw | grep -B2 -A5 'FAIL\|Error\|exit code'
[LastResort]Full log grep -- only when --failed + --tail + artifacts insufficient

[Phase3:DIFF]Why did it break? Compares status + tests + params + VCS changes
teamcity run diff <failing-id> <passing-id>
teamcity run diff <failing-id> <passing-id> --log

[Token Efficiency]Table output wastes tokens on alignment -- use --json with field selection
teamcity run list --job <id> --limit 5 --json=id,status,branchName,statusText
teamcity run tests <id> --failed --json
teamcity run log <id> --failed --json
teamcity run show <id> --json
[FieldSets]quick:--json=id,status,branchName,statusText|timed:--json=id,status,branchName,startDate,finishDate|full:--json

[Artifacts]Structured reports > log scraping -- download to /tmp then Read
teamcity run artifacts <id> --path artifacts/cicd/pipelines
[Common Artifacts]golangci-lint-report.json=structured lint findings|teamcity.stderr=pipeline stderr|e2e-results.xml=JUnit XML
[Lint Report]jq '.Issues[] | {linter:.FromLinter,text:.Text,file:.Pos.Filename,line:.Pos.Line}' /tmp/tc-lint/.../golangci-lint-report.json

[Common Failure Patterns]
lint(exit code 2, step 6)->teamcity run log <id> --failed->download golangci-lint-report.json artifact
test failure->teamcity run tests <id> --failed (--json for parsing)
integration flake(transient)->teamcity run diff <fail> <pass>|same unrelated test=transient->re-run
version mismatch->GH Actions check not TC|fix:ensure version constants match across build files

[Queue Diagnostics]Build stuck in queue -> diagnose why + whether it will ever run
[Step1]teamcity queue list --json 2>&1 | jq ".build[] | select(.buildTypeId | test(\"<your-project>\")) | {id,waitReason,queuedDate}"
[Step2]Check pool capacity:teamcity agent list --json 2>&1 | jq "[.agent[] | select(.pool.name==\"<your-pool>\")] | {total:length,connected:[.[]|select(.connected)]|length,idle:[.[]|select(.connected and (.build==null))]|length}"
[Step3]Check compatible agents:teamcity api "/app/rest/agents?locator=compatible:(buildType:(id:<job-id>))" --raw 2>&1 | jq .count
[Step4]If 0 compatible->check why:teamcity agent jobs <agent-id> --incompatible 2>&1 | grep -i <pattern>
[Verdict]idle agents > 0 + build queued = temporary backlog, will clear|compatible = 0 = pool/requirement mismatch, WILL NOT RUN -> escalate|"dependencies" = upstream must finish first -> check that build|"maximum" = concurrency limit -> will run when current finishes

[Wait Reasons]"no idle compatible agents"=all busy, will run eventually|"maximum number of running builds"=concurrency cap, will clear|"build dependencies have not been finished"=snapshot dep waiting|"agent requirements not met"=pool/capability mismatch, may NEVER run

[API Escape Hatch]teamcity api "/app/rest/<endpoint>" --raw|Raw REST when CLI lacks a feature
[API:Problems]teamcity api "/app/rest/problemOccurrences?locator=build:(id:<id>)" --raw|Structured problem list without full log
[API:Build]teamcity api "/app/rest/builds/id:<id>" --raw | jq ".status,.statusText"|Quick status check

[Anti-Patterns]
NEVER:read full teamcity run log <id> raw (60K+ lines)
NEVER:grep full log as first step -- use --failed first
NEVER:start/cancel/restart builds -- read-only
NEVER:download build binaries (20MB+ each)
NEVER:use --follow (live builds, user triggers)
