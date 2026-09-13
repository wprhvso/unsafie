<svelte:head><title>Documentation — unsafie CI</title></svelte:head>

<div class="docs-wrap">
  <h1>unsafie CI/CD Documentation</h1>
  <p class="subtitle">Zero-YAML native automation using <code>justfile</code> and <code>Makefile</code></p>

  <div class="card">
    <h2>1. Core Concepts</h2>
    <p>Unlike traditional GitHub Actions, unsafie CI doesn't use complex <code>.github/workflows/*.yml</code> files. Your builds are declared using standard project command runners: <strong>justfile</strong> (preferred) or <strong>Makefile</strong>.</p>

    <ul>
      <li><strong>Target <code>ci</code>:</strong> Runs on <em>every</em> push (branches and pull requests). Runs without production secrets.</li>
      <li><strong>Target <code>cd</code>:</strong> Runs <em>only</em> on pushes to the default branch (<code>main</code>/<code>master</code>) and <em>only</em> if the <code>ci</code> target succeeds. Injects CD secrets into the environment.</li>
      <li><strong>Root Execution:</strong> Builds run directly on the host server as root. Compilers and package managers (cargo, uv, npm, docker) maintain hot disk caches between runs.</li>
    </ul>
  </div>

  <div class="card">
    <h2>2. Example <code>justfile</code> (Recommended)</h2>
    <p>Create a <code>justfile</code> in the root of your repository:</p>
    <pre class="code-box"># Run tests, lints and verification (runs on every push)
ci:
    cargo check
    cargo test --workspace
    cargo clippy -- -D warnings

# Deploy application to production (runs ONLY on push to main)
cd:
    echo "Deploying to production..."
    docker build -t registry.unsafie.com/my-app:latest .
    docker push registry.unsafie.com/my-app:latest
    systemctl restart my-app</pre>
  </div>

  <div class="card">
    <h2>3. Example <code>Makefile</code> (Fallback)</h2>
    <p>If you prefer <code>make</code>, define <code>ci</code> and <code>cd</code> targets:</p>
    <pre class="code-box">.PHONY: ci cd

ci:
	uv run ruff check .
	uv run pytest

cd:
	uv build
	echo "Deploying artifact..."</pre>
  </div>

  <div class="card">
    <h2>4. Environment Variables Provided</h2>
    <p>Every step receives standard CI variables:</p>
    <ul>
      <li><code>CI=true</code> and <code>UNSAFIE_CI=true</code></li>
      <li><code>GITHUB_SHA</code> — Commit SHA of the triggered build</li>
      <li><code>GITHUB_REF</code> — Full git ref (e.g. <code>refs/heads/main</code>)</li>
      <li><code>GITHUB_BRANCH</code> — Branch name (e.g. <code>main</code>, <code>feature/login</code>)</li>
      <li><code>GITHUB_REPOSITORY</code> — Repository slug (e.g. <code>wprhvso/my-service</code>)</li>
      <li><strong>Custom Secrets:</strong> Injected exclusively during the <code>cd</code> target on the default branch.</li>
    </ul>
  </div>

  <div class="card">
    <h2>5. Managing Secrets via API</h2>
    <p>You can upload and update CD secrets via <code>curl</code> using a Personal CI Token:</p>
    <pre class="code-box"># Upload .env file
curl -X PUT https://ci.unsafie.com/api/ci/secrets/owner/repo/bulk \
  -H "Authorization: Bearer uci_live_YOUR_TOKEN" \
  -H "Content-Type: text/plain" \
  --data-binary @.env.production</pre>
  </div>
</div>

<style>
  .docs-wrap { max-width: 900px; margin: 0 auto; }
  h1 { font-size: 1.8rem; margin: 0 0 0.3rem; }
  .subtitle { color: var(--muted, #94a3b8); font-size: 0.95rem; margin: 0 0 1.8rem; }
  .card { background: var(--panel, #111827); border: 1px solid var(--border, #1e293b); border-radius: 10px; padding: 1.4rem 1.6rem; margin-bottom: 1.5rem; }
  h2 { font-size: 1.2rem; margin: 0 0 0.8rem; color: #38bdf8; }
  p { line-height: 1.6; color: #cbd5e1; margin: 0 0 0.8rem; font-size: 0.92rem; }
  ul { margin: 0 0 0.8rem; padding-left: 1.3rem; color: #cbd5e1; font-size: 0.92rem; line-height: 1.6; }
  li { margin-bottom: 0.4rem; }
  code { background: rgba(255,255,255,0.06); padding: 0.15rem 0.4rem; border-radius: 4px; color: #facc15; font-size: 0.85rem; font-family: monospace; }
  .code-box { background: #000; border: 1px solid var(--border, #1e293b); border-radius: 6px; padding: 1rem; font-family: monospace; font-size: 0.84rem; color: #e2e8f0; overflow-x: auto; line-height: 1.5; margin-top: 0.6rem; }
</style>
