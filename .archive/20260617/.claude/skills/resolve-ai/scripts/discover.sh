#!/bin/bash
# discover.sh - Deterministic repo scanner that outputs clean JSON to stdout.
# Status/progress messages go to stderr only. JSON goes to stdout only.
# No dependency on jq or yq.

set -e

# ---------------------------------------------------------------------------
# Directory context
# ---------------------------------------------------------------------------
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if git rev-parse --show-toplevel &>/dev/null; then
    REPO_ROOT="$(git rev-parse --show-toplevel)"
else
    REPO_ROOT="$(pwd)"
fi

cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# json_escape: escape special characters so the value is safe inside a
# JSON double-quoted string.
json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"       # backslash
    s="${s//\"/\\\"}"       # double-quote
    s="${s//$'\t'/\\t}"     # tab
    s="${s//$'\n'/\\n}"     # newline
    s="${s//$'\r'/\\r}"     # carriage return
    printf '%s' "$s"
}

# json_array: read newline-delimited items from stdin, emit a JSON array.
# Empty input produces []. Blank lines are skipped.
json_array() {
    local items=()
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        items+=("$(json_escape "$line")")
    done

    if [ "${#items[@]}" -eq 0 ]; then
        printf '[]'
        return
    fi

    printf '['
    local first=true
    for item in "${items[@]}"; do
        if [ "$first" = true ]; then
            first=false
        else
            printf ', '
        fi
        printf '"%s"' "$item"
    done
    printf ']'
}

# count_lines: count non-empty lines from a variable. Safe with set -e.
count_lines() {
    local input="$1"
    local count
    count="$(printf '%s\n' "$input" | grep -c . 2>/dev/null)" || count=0
    printf '%d' "$count"
}

# yaml_field: read a flat YAML field from a file.
# Usage: yaml_field <file> <field-name>
yaml_field() {
    local file="$1" field="$2"
    if [ ! -f "$file" ]; then
        printf ''
        return
    fi
    local raw
    raw="$(grep -E "^${field}:" "$file" 2>/dev/null | head -1 | sed "s/^${field}:[[:space:]]*//" | sed 's/[[:space:]]*$//')" || true
    # Strip surrounding quotes
    raw="${raw#\"}"
    raw="${raw%\"}"
    raw="${raw#\'}"
    raw="${raw%\'}"
    printf '%s' "$raw"
}

# ---------------------------------------------------------------------------
# 1. Software Catalog
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x94\x8d Scanning software-catalog...\n'

SOFTWARE_CATALOG=""
if [ -f "software-catalog.yaml" ]; then
    SOFTWARE_CATALOG="software-catalog.yaml"
elif [ -f "software-catalog.yml" ]; then
    SOFTWARE_CATALOG="software-catalog.yml"
fi

SOFTWARE_CATALOG_FOUND="false"
SERVICE_NAME="unknown"
SERVICE_ID=""
DESCRIPTION=""
POD_OWNER="unknown"
EMERGENCY_CONTACT=""
BUSINESS_RISK="Unknown"
SECURITY_RISK="Unknown"
EXPOSURE="unknown"
SERVICE_TYPE="unknown"
PRODUCT_FAMILY="unknown"

if [ -n "$SOFTWARE_CATALOG" ]; then
    SOFTWARE_CATALOG_FOUND="true"

    val="$(yaml_field "$SOFTWARE_CATALOG" "service-name")"
    [ -n "$val" ] && SERVICE_NAME="$val"

    val="$(yaml_field "$SOFTWARE_CATALOG" "service-id")"
    [ -n "$val" ] && SERVICE_ID="$val"

    val="$(yaml_field "$SOFTWARE_CATALOG" "description")"
    [ -n "$val" ] && DESCRIPTION="$val"

    val="$(yaml_field "$SOFTWARE_CATALOG" "pod-owner")"
    [ -n "$val" ] && POD_OWNER="$val"

    val="$(yaml_field "$SOFTWARE_CATALOG" "emergency-contact")"
    [ -n "$val" ] && EMERGENCY_CONTACT="$val"

    val="$(yaml_field "$SOFTWARE_CATALOG" "business-risk")"
    [ -n "$val" ] && BUSINESS_RISK="$val"

    val="$(yaml_field "$SOFTWARE_CATALOG" "security-risk")"
    [ -n "$val" ] && SECURITY_RISK="$val"

    val="$(yaml_field "$SOFTWARE_CATALOG" "exposure")"
    [ -n "$val" ] && EXPOSURE="$val"

    val="$(yaml_field "$SOFTWARE_CATALOG" "service-type")"
    [ -n "$val" ] && SERVICE_TYPE="$val"

    val="$(yaml_field "$SOFTWARE_CATALOG" "product-family")"
    [ -n "$val" ] && PRODUCT_FAMILY="$val"

    >&2 printf '\xe2\x9c\x93 Found %s\n' "$SOFTWARE_CATALOG"
else
    >&2 printf '\xe2\x9a\xa0 No software-catalog.yaml found\n'
fi

# ---------------------------------------------------------------------------
# 2. Language / Stack
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x94\x8d Detecting languages...\n'

LANGUAGES_RAW=""
detect_lang() {
    local file="$1" lang="$2"
    if [ -f "$file" ]; then
        LANGUAGES_RAW="${LANGUAGES_RAW}${lang}"$'\n'
    fi
}

detect_lang "go.mod"            "go"
detect_lang "package.json"      "node"
detect_lang "pom.xml"           "java"
detect_lang "build.gradle"      "java"
detect_lang "requirements.txt"  "python"
detect_lang "pyproject.toml"    "python"
detect_lang "Cargo.toml"        "rust"
detect_lang "Gemfile"           "ruby"
detect_lang "composer.json"     "php"

LANGUAGES_DEDUP="$(printf '%s\n' "$LANGUAGES_RAW" | grep -v '^$' | awk '!seen[$0]++' || true)"
LANGUAGES_JSON="$(printf '%s\n' "$LANGUAGES_DEDUP" | json_array)"

PRIMARY_LANGUAGE="unknown"
first_lang="$(printf '%s\n' "$LANGUAGES_DEDUP" | head -1)"
[ -n "$first_lang" ] && PRIMARY_LANGUAGE="$first_lang"

>&2 printf '\xe2\x9c\x93 Languages: %s\n' "${PRIMARY_LANGUAGE}"

# ---------------------------------------------------------------------------
# 3. Services (Dockerfiles & docker-compose)
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x94\x8d Detecting services...\n'

SERVICES_RAW=""

# Find Dockerfiles (maxdepth 3)
while IFS= read -r df; do
    [ -z "$df" ] && continue
    dir="$(dirname "$df")"
    base="$(basename "$dir")"
    [ "$dir" = "." ] && base="root"
    SERVICES_RAW="${SERVICES_RAW}dockerfile:${base}"$'\n'
done < <(find . -maxdepth 3 -name 'Dockerfile' -o -name 'Dockerfile.*' 2>/dev/null | sed 's|^\./||')

# Extract service names from docker-compose files
while IFS= read -r dcf; do
    [ -z "$dcf" ] && continue
    in_services=false
    while IFS= read -r line; do
        if printf '%s' "$line" | grep -qE '^services:'; then
            in_services=true
            continue
        fi
        if [ "$in_services" = true ]; then
            if printf '%s' "$line" | grep -qE '^[a-zA-Z]'; then
                in_services=false
                continue
            fi
            svc="$(printf '%s' "$line" | grep -oE '^[[:space:]]{2,4}[a-zA-Z_][a-zA-Z0-9_-]*:' | sed 's/^[[:space:]]*//' | sed 's/:$//')" || true
            [ -n "$svc" ] && SERVICES_RAW="${SERVICES_RAW}compose:${svc}"$'\n'
        fi
    done < "$dcf"
done < <(find . -maxdepth 3 \( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'docker-compose.*.yml' -o -name 'docker-compose.*.yaml' \) 2>/dev/null | sed 's|^\./||')

SERVICES_DEDUP="$(printf '%s\n' "$SERVICES_RAW" | grep -v '^$' | awk '!seen[$0]++' || true)"
SERVICES_JSON="$(printf '%s\n' "$SERVICES_DEDUP" | json_array)"

>&2 printf '\xe2\x9c\x93 Services detected: %d\n' "$(count_lines "$SERVICES_DEDUP")"

# ---------------------------------------------------------------------------
# 4. Kubernetes
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x94\x8d Scanning Kubernetes config...\n'

K8S_NAMESPACES_RAW=""
K8S_ENVIRONMENTS_RAW=""
HAS_HELM="false"
HAS_KUSTOMIZE="false"

K8S_DIRS=""
for d in k8s kubernetes deploy manifests; do
    [ -d "$d" ] && K8S_DIRS="${K8S_DIRS} ${d}"
done

if find . -maxdepth 4 -name 'Chart.yaml' 2>/dev/null | grep -q .; then
    HAS_HELM="true"
fi
if find . -maxdepth 4 \( -name 'kustomization.yaml' -o -name 'kustomization.yml' \) 2>/dev/null | grep -q .; then
    HAS_KUSTOMIZE="true"
fi

if [ -n "$K8S_DIRS" ]; then
    for d in $K8S_DIRS; do
        while IFS= read -r ns; do
            [ -z "$ns" ] && continue
            K8S_NAMESPACES_RAW="${K8S_NAMESPACES_RAW}${ns}"$'\n'
        done < <(grep -rh 'namespace:' "$d" 2>/dev/null \
            | sed 's/.*namespace:[[:space:]]*//' \
            | sed 's/[[:space:]]*$//' \
            | sed 's/^"//' | sed 's/"$//' \
            | sed "s/^'//" | sed "s/'$//" \
            | grep -v '^$' | grep -v '{{' || true)

        while IFS= read -r envdir; do
            [ -z "$envdir" ] && continue
            base="$(basename "$envdir")"
            case "$base" in
                dev|development|staging|stage|stg|production|prod|qa|uat|sandbox|test)
                    K8S_ENVIRONMENTS_RAW="${K8S_ENVIRONMENTS_RAW}${base}"$'\n'
                    ;;
            esac
        done < <(find "$d" -maxdepth 2 -type d 2>/dev/null)
    done
fi

[ -f "Chart.yaml" ] && HAS_HELM="true"
[ -f "kustomization.yaml" ] || [ -f "kustomization.yml" ] && HAS_KUSTOMIZE="true"

K8S_NAMESPACES_DEDUP="$(printf '%s\n' "$K8S_NAMESPACES_RAW" | grep -v '^$' | awk '!seen[$0]++' || true)"
K8S_ENVIRONMENTS_DEDUP="$(printf '%s\n' "$K8S_ENVIRONMENTS_RAW" | grep -v '^$' | awk '!seen[$0]++' || true)"
K8S_NAMESPACES_JSON="$(printf '%s\n' "$K8S_NAMESPACES_DEDUP" | json_array)"
K8S_ENVIRONMENTS_JSON="$(printf '%s\n' "$K8S_ENVIRONMENTS_DEDUP" | json_array)"

>&2 printf '\xe2\x9c\x93 Kubernetes: helm=%s kustomize=%s\n' "$HAS_HELM" "$HAS_KUSTOMIZE"

# ---------------------------------------------------------------------------
# 5. Datadog Monitors
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x94\x8d Scanning Datadog monitors...\n'

DD_MONITORS_RAW=""

while IFS= read -r mf; do
    [ -z "$mf" ] && continue
    DD_MONITORS_RAW="${DD_MONITORS_RAW}${mf}"$'\n'
done < <(find . -maxdepth 4 \( -name '*.monitor.yaml' -o -name '*.monitor.yml' -o -name '*.monitor.json' \) 2>/dev/null | sed 's|^\./||')

for d in monitors datadog; do
    if [ -d "$d" ]; then
        while IFS= read -r mf; do
            [ -z "$mf" ] && continue
            DD_MONITORS_RAW="${DD_MONITORS_RAW}${mf}"$'\n'
        done < <(find "$d" -maxdepth 3 -type f \( -name '*.yaml' -o -name '*.yml' -o -name '*.json' \) 2>/dev/null | sed 's|^\./||')
    fi
done

while IFS= read -r tf; do
    [ -z "$tf" ] && continue
    if grep -q 'datadog_monitor' "$tf" 2>/dev/null; then
        DD_MONITORS_RAW="${DD_MONITORS_RAW}tf:${tf}"$'\n'
    fi
done < <(find . -maxdepth 4 -name '*.tf' 2>/dev/null | sed 's|^\./||')

DD_MONITORS_DEDUP="$(printf '%s\n' "$DD_MONITORS_RAW" | grep -v '^$' | awk '!seen[$0]++' || true)"
DD_MONITORS_JSON="$(printf '%s\n' "$DD_MONITORS_DEDUP" | json_array)"

>&2 printf '\xe2\x9c\x93 Datadog monitors: %d\n' "$(count_lines "$DD_MONITORS_DEDUP")"

# ---------------------------------------------------------------------------
# 6. Infrastructure
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x94\x8d Detecting infrastructure...\n'

INFRA_PROVIDER="unknown"
TF_FILES="$(find . -maxdepth 4 -name '*.tf' 2>/dev/null | head -1)"

if [ -n "$TF_FILES" ]; then
    if grep -rq 'provider "aws"' --include='*.tf' . 2>/dev/null; then
        INFRA_PROVIDER="aws"
    elif grep -rq 'provider "google"' --include='*.tf' . 2>/dev/null; then
        INFRA_PROVIDER="gcp"
    elif grep -rq 'provider "azurerm"' --include='*.tf' . 2>/dev/null; then
        INFRA_PROVIDER="azure"
    else
        INFRA_PROVIDER="terraform-other"
    fi
fi

>&2 printf '\xe2\x9c\x93 Infra provider: %s\n' "$INFRA_PROVIDER"

# ---------------------------------------------------------------------------
# 7. Existing Docs
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x94\x8d Checking existing documentation...\n'

DOCS_RAW=""
HAS_EXISTING_RESOLVE_MD="false"

for doc in README.md README.rst README.txt ARCHITECTURE.md CONTRIBUTING.md CHANGELOG.md; do
    [ -f "$doc" ] && DOCS_RAW="${DOCS_RAW}${doc}"$'\n'
done

[ -d "docs" ] && DOCS_RAW="${DOCS_RAW}docs/"$'\n'

if [ -f "RESOLVE.md" ]; then
    HAS_EXISTING_RESOLVE_MD="true"
    DOCS_RAW="${DOCS_RAW}RESOLVE.md"$'\n'
fi

DOCS_JSON="$(printf '%s\n' "$DOCS_RAW" | json_array)"

>&2 printf '\xe2\x9c\x93 Docs found: %d items, RESOLVE.md=%s\n' "$(count_lines "$DOCS_RAW")" "$HAS_EXISTING_RESOLVE_MD"

# ---------------------------------------------------------------------------
# 8. Datastores
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x94\x8d Detecting datastores...\n'

DATASTORES_RAW=""

# From docker-compose files
while IFS= read -r dcf; do
    [ -z "$dcf" ] && continue
    for img in postgres mysql mariadb redis mongodb mongo elasticsearch opensearch rabbitmq kafka memcached dynamodb cassandra minio; do
        if grep -qi "image:.*${img}" "$dcf" 2>/dev/null || grep -qi "/${img}" "$dcf" 2>/dev/null; then
            DATASTORES_RAW="${DATASTORES_RAW}${img}"$'\n'
        fi
    done
done < <(find . -maxdepth 3 \( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'docker-compose.*.yml' -o -name 'docker-compose.*.yaml' \) 2>/dev/null | sed 's|^\./||')

# From terraform
if [ -n "$TF_FILES" ]; then
    for resource in aws_rds aws_db_instance aws_elasticache google_sql_database azurerm_postgresql azurerm_mysql aws_dynamodb_table aws_sqs_queue aws_kinesis; do
        if grep -rq "$resource" --include='*.tf' . 2>/dev/null; then
            case "$resource" in
                aws_rds|aws_db_instance)  DATASTORES_RAW="${DATASTORES_RAW}rds"$'\n' ;;
                aws_elasticache)          DATASTORES_RAW="${DATASTORES_RAW}elasticache"$'\n' ;;
                google_sql_database)      DATASTORES_RAW="${DATASTORES_RAW}google-cloud-sql"$'\n' ;;
                azurerm_postgresql)       DATASTORES_RAW="${DATASTORES_RAW}azure-postgresql"$'\n' ;;
                azurerm_mysql)            DATASTORES_RAW="${DATASTORES_RAW}azure-mysql"$'\n' ;;
                aws_dynamodb_table)       DATASTORES_RAW="${DATASTORES_RAW}dynamodb"$'\n' ;;
                aws_sqs_queue)            DATASTORES_RAW="${DATASTORES_RAW}sqs"$'\n' ;;
                aws_kinesis)              DATASTORES_RAW="${DATASTORES_RAW}kinesis"$'\n' ;;
            esac
        fi
    done
fi

# From env files
for envfile in .env.example .env.sample .env.template; do
    if [ -f "$envfile" ] && grep -q 'DATABASE_URL' "$envfile" 2>/dev/null; then
        db_url="$(grep 'DATABASE_URL' "$envfile" 2>/dev/null | head -1 | sed 's/.*DATABASE_URL[[:space:]]*=[[:space:]]*//')"
        case "$db_url" in
            postgres*)  DATASTORES_RAW="${DATASTORES_RAW}postgres"$'\n' ;;
            mysql*)     DATASTORES_RAW="${DATASTORES_RAW}mysql"$'\n' ;;
            sqlite*)    DATASTORES_RAW="${DATASTORES_RAW}sqlite"$'\n' ;;
            mongodb*)   DATASTORES_RAW="${DATASTORES_RAW}mongodb"$'\n' ;;
            *)          DATASTORES_RAW="${DATASTORES_RAW}database-url-detected"$'\n' ;;
        esac
    fi
done

DATASTORES_DEDUP="$(printf '%s\n' "$DATASTORES_RAW" | grep -v '^$' | awk '!seen[$0]++' || true)"
DATASTORES_JSON="$(printf '%s\n' "$DATASTORES_DEDUP" | json_array)"

>&2 printf '\xe2\x9c\x93 Datastores: %d\n' "$(count_lines "$DATASTORES_DEDUP")"

# ---------------------------------------------------------------------------
# 9. SLO Config
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x94\x8d Checking SLO configuration...\n'

HAS_SLO="false"
if grep -rqlE 'slo[^a-zA-Z]|service_level_objective|error_budget' \
    --include='*.tf' --include='*.yaml' --include='*.yml' --include='*.json' \
    . 2>/dev/null | grep -v node_modules | grep -v '.git' | head -1 | grep -q .; then
    HAS_SLO="true"
fi

>&2 printf '\xe2\x9c\x93 SLO config: %s\n' "$HAS_SLO"

# ---------------------------------------------------------------------------
# 10. Gaps
# ---------------------------------------------------------------------------
>&2 printf '\xf0\x9f\x93\x8a Computing gaps...\n'

GAPS_RAW=""

[ "$SOFTWARE_CATALOG_FOUND" = "false" ] && GAPS_RAW="${GAPS_RAW}no_software_catalog"$'\n'

if [ -z "$K8S_DIRS" ] && [ "$HAS_HELM" = "false" ] && [ "$HAS_KUSTOMIZE" = "false" ]; then
    GAPS_RAW="${GAPS_RAW}no_k8s_manifests"$'\n'
fi

dd_count="$(count_lines "$DD_MONITORS_DEDUP")"
[ "$dd_count" -eq 0 ] && GAPS_RAW="${GAPS_RAW}no_datadog_monitors"$'\n'

[ "$HAS_SLO" = "false" ] && GAPS_RAW="${GAPS_RAW}no_slo_config"$'\n'

ds_count="$(count_lines "$DATASTORES_DEDUP")"
[ "$ds_count" -eq 0 ] && GAPS_RAW="${GAPS_RAW}no_datastores_detected"$'\n'

[ "$INFRA_PROVIDER" = "unknown" ] && GAPS_RAW="${GAPS_RAW}no_infrastructure"$'\n'

[ "$PRIMARY_LANGUAGE" = "unknown" ] && GAPS_RAW="${GAPS_RAW}unknown_language"$'\n'

GAPS_JSON="$(printf '%s\n' "$GAPS_RAW" | json_array)"

>&2 printf '\xe2\x9c\x93 Gaps identified: %d\n' "$(count_lines "$GAPS_RAW")"

# ---------------------------------------------------------------------------
# Output JSON to stdout
# ---------------------------------------------------------------------------
>&2 printf '\xe2\x9c\x85 Discovery complete. Emitting JSON.\n'

cat <<ENDJSON
{
  "service_name": "$(json_escape "$SERVICE_NAME")",
  "service_id": "$(json_escape "$SERVICE_ID")",
  "description": "$(json_escape "$DESCRIPTION")",
  "pod_owner": "$(json_escape "$POD_OWNER")",
  "emergency_contact": "$(json_escape "$EMERGENCY_CONTACT")",
  "business_risk": "$(json_escape "$BUSINESS_RISK")",
  "security_risk": "$(json_escape "$SECURITY_RISK")",
  "exposure": "$(json_escape "$EXPOSURE")",
  "service_type": "$(json_escape "$SERVICE_TYPE")",
  "product_family": "$(json_escape "$PRODUCT_FAMILY")",
  "language": "$(json_escape "$PRIMARY_LANGUAGE")",
  "languages": ${LANGUAGES_JSON},
  "services": ${SERVICES_JSON},
  "k8s": {
    "namespaces": ${K8S_NAMESPACES_JSON},
    "environments": ${K8S_ENVIRONMENTS_JSON},
    "has_helm": ${HAS_HELM},
    "has_kustomize": ${HAS_KUSTOMIZE}
  },
  "infra_provider": "$(json_escape "$INFRA_PROVIDER")",
  "datadog_monitors": ${DD_MONITORS_JSON},
  "datastores": ${DATASTORES_JSON},
  "existing_docs": ${DOCS_JSON},
  "has_existing_resolve_md": ${HAS_EXISTING_RESOLVE_MD},
  "has_slo": ${HAS_SLO},
  "software_catalog_found": ${SOFTWARE_CATALOG_FOUND},
  "gaps": ${GAPS_JSON}
}
ENDJSON
