#!/bin/bash
for pr in 893 889 887 883 880 879 857; do
    branch=$(gh pr view $pr --json headRefName -q .headRefName)
    echo "Processing $branch"
    git checkout $branch
    git pull origin $branch
    git merge main --no-commit
    git checkout main -- uv.lock requirements.lock pyproject.toml docs/product-technical-gap-baseline.md 2>/dev/null
    git add .
    git commit -m "Merge main and resolve conflicts"
    git push origin $branch
done
