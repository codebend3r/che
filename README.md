## Shell Functions

> a list of shell functions to share amongst computers

## Getting Started

- pull the latest changes from the main branch
- if the script is new, add it to your `.zshrc` file

## Running tests

This repo uses [Bun](https://bun.sh) as its default package runner.

```sh
bun run test
```

Under the hood the `test` script delegates to `bash test/run-all.sh`, so Bun is only orchestrating — the suites themselves stay pure bash. (Note: plain `bun test` invokes Bun's built-in JS/TS test runner, which doesn't apply here — always use `bun run test`.)