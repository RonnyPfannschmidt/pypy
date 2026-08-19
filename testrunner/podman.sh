#!/bin/bash
# Run the RPython test suite locally in the same container CI uses.
#
#   testrunner/podman.sh                        # full suite, as CI runs it
#   testrunner/podman.sh --suite rlib           # one CI suite
#   testrunner/podman.sh rpython/tool/test      # pytest on given paths
#   testrunner/podman.sh -- -k test_pairtype rpython/tool/test
#   testrunner/podman.sh --shell                # interactive shell
#
# The image is read out of .github/workflows/rpython-unit-tests.yml, so this
# cannot drift away from what CI actually uses.  Set PYPY_CI_IMAGE to override.
#
# Requires podman (or docker, via CONTAINER_ENGINE=docker).

set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
workflow="$here/.github/workflows/rpython-unit-tests.yml"
engine=${CONTAINER_ENGINE:-podman}

case "$(uname -m)" in
    aarch64|arm64) worker=buildworker_aarch64 ;;
    *)             worker=buildworker_x86_64 ;;
esac

if [ -z "${PYPY_CI_IMAGE:-}" ]; then
    if [ ! -f "$workflow" ]; then
        echo "$workflow not found; set PYPY_CI_IMAGE instead" >&2
        exit 2
    fi
    PYPY_CI_IMAGE=$(grep -oE "ghcr\.io/pypy/${worker}@sha256:[0-9a-f]+" \
                    "$workflow" | head -1)
    if [ -z "$PYPY_CI_IMAGE" ]; then
        echo "no $worker image found in $workflow; set PYPY_CI_IMAGE" >&2
        exit 2
    fi
fi

# The CI suites, kept in step with the case statement in the workflow.
suite_dirs() {
    case "$1" in
        misc)      echo "annotator:config:flowspace:tool:rtyper:memory" ;;
        rlib)      echo "rlib" ;;
        translator) echo "translator" ;;
        jit-arch)  case "$worker" in
                       *aarch64) echo "jit/backend/aarch64" ;;
                       *)        echo "jit/backend/x86" ;;
                   esac ;;
        jit-other) echo "jit/metainterp:jit/codewriter:jit/tl:jit/tool:jit/backend/arm:jit/backend/llgraph:jit/backend/llsupport:jit/backend/ppc:jit/backend/riscv:jit/backend/test:jit/backend/tool:jit/backend/zarch" ;;
        *)         echo "unknown suite: $1" >&2; exit 2 ;;
    esac
}

mode=runner
cherrypick=""
paths=()
while [ $# -gt 0 ]; do
    case "$1" in
        --suite) cherrypick=$(suite_dirs "$2"); shift 2 ;;
        --shell) mode=shell; shift ;;
        --)      shift; mode=pytest; paths+=("$@"); break ;;
        -*)      mode=pytest; paths+=("$1"); shift ;;
        *)       mode=pytest; paths+=("$1"); shift ;;
    esac
done

jobs=${PYPY_TEST_JOBS:-$(nproc 2>/dev/null || echo 4)}

run() {
    # :z relabels for SELinux; rootless podman maps container root to the
    # invoking user, so files the tests write stay owned by you.
    exec "$engine" run --rm -it \
        -v "$here:/workspace:z" \
        -w /workspace \
        -e PYTHONPATH=. \
        -e PYPYCHERRYPICK="$cherrypick" \
        "$PYPY_CI_IMAGE" \
        "$@"
}

case "$mode" in
    shell)
        run bash
        ;;
    pytest)
        run pypy pytest.py "${paths[@]}"
        ;;
    runner)
        echo "parallel_runs=$jobs" > "$here/machine_cfg.py"
        run pypy testrunner/runner.py \
            --config=pypy/testrunner_cfg.py \
            --config=machine_cfg.py \
            --root=rpython \
            --timeout=1759 \
            --logfile=testrun.log
        ;;
esac
