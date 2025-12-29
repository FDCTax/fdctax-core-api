#!/bin/bash
# FDC Core - Post-Deployment Verification Script
# Verifies that the deployed backend is functioning correctly
#
# Usage: ./verify_deployment.sh <API_URL>
# Example: ./verify_deployment.sh https://api.fdccore.com

set -e

API_URL=${1:-"http://localhost:8001"}
TEST_RESULTS=()
FAILED=0

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_success() {
    echo -e "${GREEN}✓${NC} $1"
    TEST_RESULTS+=("PASS: $1")
}

log_failure() {
    echo -e "${RED}✗${NC} $1"
    TEST_RESULTS+=("FAIL: $1")
    FAILED=1
}

log_info() {
    echo -e "${YELLOW}●${NC} $1"
}

echo "============================================="
echo "FDC Core - Post-Deployment Verification"
echo "API URL: $API_URL"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "============================================="

# ==================== 1. HEALTH CHECKS ====================
log_info "Testing health endpoints..."

# Basic health
HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" "$API_URL/api/" 2>/dev/null)
HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -n1)
BODY=$(echo "$HEALTH_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    STATUS=$(echo "$BODY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('status',''))" 2>/dev/null || echo "")
    if [ "$STATUS" = "healthy" ]; then
        log_success "Basic health check passed (status=healthy)"
    else
        log_failure "Basic health check failed (status=$STATUS)"
    fi
else
    log_failure "Basic health check failed (HTTP $HTTP_CODE)"
fi

# Detailed health with DB check
HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" "$API_URL/api/health" 2>/dev/null)
HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -n1)
BODY=$(echo "$HEALTH_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    DB_STATUS=$(echo "$BODY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('checks',{}).get('database',{}).get('status',''))" 2>/dev/null || echo "")
    if [ "$DB_STATUS" = "connected" ]; then
        log_success "Database connection verified"
    else
        log_failure "Database not connected (status=$DB_STATUS)"
    fi
else
    log_failure "Detailed health check failed (HTTP $HTTP_CODE)"
fi

# Kubernetes probes
for PROBE in "ready" "live"; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/health/$PROBE" 2>/dev/null)
    if [ "$HTTP_CODE" = "200" ]; then
        log_success "Kubernetes ${PROBE}ness probe passed"
    else
        log_failure "Kubernetes ${PROBE}ness probe failed (HTTP $HTTP_CODE)"
    fi
done

# ==================== 2. AUTHENTICATION ====================
log_info "Testing authentication..."

# Test admin login
ADMIN_RESPONSE=$(curl -s -X POST "$API_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@fdctax.com","password":"admin123"}' 2>/dev/null)
ADMIN_ROLE=$(echo "$ADMIN_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('role',''))" 2>/dev/null || echo "")

if [ "$ADMIN_ROLE" = "admin" ]; then
    log_success "Admin authentication works (role=admin)"
    ADMIN_TOKEN=$(echo "$ADMIN_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('access_token',''))" 2>/dev/null)
else
    log_failure "Admin authentication failed (role=$ADMIN_ROLE)"
fi

# Test staff login
STAFF_RESPONSE=$(curl -s -X POST "$API_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"staff@fdctax.com","password":"staff123"}' 2>/dev/null)
STAFF_ROLE=$(echo "$STAFF_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('role',''))" 2>/dev/null || echo "")

if [ "$STAFF_ROLE" = "staff" ]; then
    log_success "Staff authentication works (role=staff)"
    STAFF_TOKEN=$(echo "$STAFF_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('access_token',''))" 2>/dev/null)
else
    log_failure "Staff authentication failed (role=$STAFF_ROLE)"
fi

# Test tax_agent login
TA_RESPONSE=$(curl -s -X POST "$API_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"taxagent@fdctax.com","password":"taxagent123"}' 2>/dev/null)
TA_ROLE=$(echo "$TA_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('role',''))" 2>/dev/null || echo "")

if [ "$TA_ROLE" = "tax_agent" ]; then
    log_success "Tax agent authentication works (role=tax_agent)"
    TA_TOKEN=$(echo "$TA_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('access_token',''))" 2>/dev/null)
else
    log_failure "Tax agent authentication failed (role=$TA_ROLE)"
fi

# Test client login
CLIENT_RESPONSE=$(curl -s -X POST "$API_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"client@fdctax.com","password":"client123"}' 2>/dev/null)
CLIENT_ROLE=$(echo "$CLIENT_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('role',''))" 2>/dev/null || echo "")

if [ "$CLIENT_ROLE" = "client" ]; then
    log_success "Client authentication works (role=client)"
    CLIENT_TOKEN=$(echo "$CLIENT_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('access_token',''))" 2>/dev/null)
else
    log_failure "Client authentication failed (role=$CLIENT_ROLE)"
fi

# ==================== 3. TRANSACTION ENGINE ====================
log_info "Testing Transaction Engine..."

# MyFDC can POST transaction
if [ -n "$CLIENT_TOKEN" ]; then
    TXN_RESPONSE=$(curl -s -X POST "$API_URL/api/myfdc/transactions?client_id=verify-deploy-$(date +%s)" \
        -H "Authorization: Bearer $CLIENT_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"date":"2024-12-29","amount":99.99,"payee":"Deployment Verification","description":"Post-deploy test"}' 2>/dev/null)
    TXN_SUCCESS=$(echo "$TXN_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('success',False))" 2>/dev/null || echo "")
    
    if [ "$TXN_SUCCESS" = "True" ]; then
        log_success "MyFDC can POST transactions"
        TXN_ID=$(echo "$TXN_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('transaction',{}).get('id',''))" 2>/dev/null)
    else
        log_failure "MyFDC cannot POST transactions"
    fi
fi

# FDC Tax can GET transactions
if [ -n "$STAFF_TOKEN" ]; then
    GET_RESPONSE=$(curl -s -X GET "$API_URL/api/bookkeeper/transactions?limit=5" \
        -H "Authorization: Bearer $STAFF_TOKEN" 2>/dev/null)
    TOTAL=$(echo "$GET_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('total',0))" 2>/dev/null || echo "0")
    
    if [ "$TOTAL" -ge 0 ]; then
        log_success "FDC Tax can GET transactions (total=$TOTAL)"
    else
        log_failure "FDC Tax cannot GET transactions"
    fi
fi

# FDC Tax can PATCH transactions
if [ -n "$STAFF_TOKEN" ] && [ -n "$TXN_ID" ]; then
    PATCH_RESPONSE=$(curl -s -X PATCH "$API_URL/api/bookkeeper/transactions/$TXN_ID" \
        -H "Authorization: Bearer $STAFF_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"notes_bookkeeper":"Verified in post-deploy check"}' 2>/dev/null)
    PATCH_ID=$(echo "$PATCH_RESPONSE" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('id',''))" 2>/dev/null || echo "")
    
    if [ "$PATCH_ID" = "$TXN_ID" ]; then
        log_success "FDC Tax can PATCH transactions"
    else
        log_failure "FDC Tax cannot PATCH transactions"
    fi
fi

# ==================== 4. CORS CHECK ====================
log_info "Testing CORS configuration..."

for ORIGIN in "https://fdctax.com" "https://myfdc.com"; do
    CORS_HEADER=$(curl -s -I -X OPTIONS "$API_URL/api/" \
        -H "Origin: $ORIGIN" \
        -H "Access-Control-Request-Method: POST" 2>/dev/null | grep -i "access-control-allow-origin" | head -1)
    
    if echo "$CORS_HEADER" | grep -q "$ORIGIN"; then
        log_success "CORS allows $ORIGIN"
    else
        log_failure "CORS does not allow $ORIGIN"
    fi
done

# ==================== 5. NO 500 ERRORS ====================
log_info "Checking for 500 errors..."

# Make several requests and check for 5xx errors
ERROR_COUNT=0
for ENDPOINT in "/api/" "/api/health" "/api/bookkeeper/statuses" "/api/bookkeeper/gst-codes"; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $STAFF_TOKEN" "$API_URL$ENDPOINT" 2>/dev/null)
    if [[ "$HTTP_CODE" =~ ^5 ]]; then
        ERROR_COUNT=$((ERROR_COUNT + 1))
    fi
done

if [ "$ERROR_COUNT" -eq 0 ]; then
    log_success "No 500 errors detected"
else
    log_failure "Detected $ERROR_COUNT endpoints returning 500 errors"
fi

# ==================== SUMMARY ====================
echo ""
echo "============================================="
echo "Verification Summary"
echo "============================================="

PASS_COUNT=0
FAIL_COUNT=0

for RESULT in "${TEST_RESULTS[@]}"; do
    if [[ "$RESULT" == PASS* ]]; then
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

echo "Passed: $PASS_COUNT"
echo "Failed: $FAIL_COUNT"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}=============================================${NC}"
    echo -e "${GREEN}✓ DEPLOYMENT VERIFICATION SUCCESSFUL${NC}"
    echo -e "${GREEN}=============================================${NC}"
    exit 0
else
    echo -e "${RED}=============================================${NC}"
    echo -e "${RED}✗ DEPLOYMENT VERIFICATION FAILED${NC}"
    echo -e "${RED}=============================================${NC}"
    echo ""
    echo "Failed tests:"
    for RESULT in "${TEST_RESULTS[@]}"; do
        if [[ "$RESULT" == FAIL* ]]; then
            echo "  - ${RESULT#FAIL: }"
        fi
    done
    exit 1
fi
