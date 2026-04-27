# broken_calc

Tiny example project for the airlock toy. `calc.py` has a bug in `add()` (it
subtracts instead of adding). The pytest cases in `test_calc.py` will fail
until Claude fixes it.

## Manual run (outside the toy)

```bash
cd examples/broken_calc
pytest -q     # 3 fail, 2 pass
```

## What Claude is expected to do

1. Read `test_calc.py` and `calc.py`.
2. Notice that `add()` returns `a - b`.
3. Fix it to return `a + b`.
4. Re-run pytest, see all 5 tests pass.
5. Commit the fix and push the branch via the host broker.
