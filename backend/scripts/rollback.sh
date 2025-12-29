#!/bin/bash
# FDC Core - Rollback Script
# Rolls back the deployment to a previous version
#
# Usage: ./rollback.sh <namespace> [revision]
# Example: ./rollback.sh fdc-production
# Example: ./rollback.sh fdc-production 3

set -e

NAMESPACE=${1:-"fdc-production"}
REVISION=${2:-""}
DEPLOYMENT="fdc-core-backend"

echo "============================================="
echo "FDC Core - Deployment Rollback"
echo "============================================="
echo "Namespace: $NAMESPACE"
echo "Deployment: $DEPLOYMENT"
echo "Revision: ${REVISION:-'Previous'}"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo ""

# Show current state
echo "Current deployment state:"
kubectl rollout history deployment/$DEPLOYMENT -n $NAMESPACE | tail -5
echo ""

# Confirm rollback
read -p "Proceed with rollback? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Rollback cancelled"
    exit 0
fi

# Perform rollback
echo "Performing rollback..."
if [ -n "$REVISION" ]; then
    kubectl rollout undo deployment/$DEPLOYMENT -n $NAMESPACE --to-revision=$REVISION
else
    kubectl rollout undo deployment/$DEPLOYMENT -n $NAMESPACE
fi

# Wait for rollback
echo "Waiting for rollback to complete..."
kubectl rollout status deployment/$DEPLOYMENT -n $NAMESPACE --timeout=300s

# Verify
echo ""
echo "Rollback complete. Current pods:"
kubectl get pods -n $NAMESPACE -l app=fdc-core,component=backend

echo ""
echo "============================================="
echo "Rollback successful"
echo "============================================="
