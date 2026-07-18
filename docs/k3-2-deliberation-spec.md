# K3-2: Council Considered — Deliberation Flow

## Summary

Add a "Council considered" section inside `templates/partials/premium/council_stage.html` that shows alternative subnets the council weighed before picking the current claim. This is a horizontal-scrolling card list inside a new collapsible layer called "Deliberation".

## Where to insert

The file is structured as:

1. **CSS** (top `<style>` block) — Add K3-2 styles at the end of the existing style block
2. **Evidence layer** — ends with `</div>` around signal rows. Insert the new Deliberation layer AFTER Evidence closes and BEFORE the Council layer (`Council▸`).
3. **HTML** — New layer section with Jinja logic
4. **JavaScript** (bottom `<script>` block) — Add `switchToSubnet()` function

## Exact changes

### 1. CSS — Add inside existing `<style>` block

Insert these styles at the end of the `<style>` block (before `</style>`):

```css
{# ---- K3-2: Council considered (deliberation flow) ---- #}
.k3-deliberation { margin-top: 16px; }
.k3-considered-list { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 8px; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
.k3-considered-list::-webkit-scrollbar { display: none; }
.k3-considered-card { min-width: 120px; background: var(--k3-surface); border-radius: 8px; padding: 10px 12px; flex-shrink: 0; -webkit-tap-highlight-color: transparent; cursor: pointer; transition: background 0.15s; border: 1px solid var(--k3-border); }
.k3-considered-card:active { background: var(--k3-surface-hover); }
.k3-considered-avatar { width: 28px; height: 28px; border-radius: 50%; background: var(--k3-accent); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; color: #fff; margin-bottom: 6px; }
.k3-considered-name { font-size: 11px; font-weight: 600; color: var(--k3-foreground); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.k3-considered-role { font-size: 10px; color: var(--k3-muted); margin: 2px 0 4px; }
.k3-considered-confidence { font-size: 12px; font-weight: 700; }
.k3-considered-stance { font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; padding: 2px 6px; border-radius: 4px; display: inline-block; margin-top: 4px; }
.k3-considered-stance--long { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
.k3-considered-stance--short { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.k3-considered-stance--hold { background: rgba(234, 179, 8, 0.15); color: #eab308; }
```

### 2. HTML — New Deliberation layer

Insert between the Evidence layer (closing `</div>` of signal rows) and the Council layer header (`Council▸`). Add this:

```html
{# ---- K3-2: Council considered (deliberation flow) ---- #}
<div class="k3-layer" id="layer-deliberation">

  <button class="k3-layer-header" onclick="toggleLayer('layer-deliberation')">
    Deliberation▸
  </button>

  <div class="k3-layer-body">
    <p class="k3-layer-subtitle">Alternatives the council weighed</p>

    {% set alternatives = dpick.shortlist if dpick.shortlist is iterable and dpick.shortlist is not string else [] %}
    {% if alternatives and alternatives|length > 0 %}
    <div class="k3-deliberation">
      <div class="k3-considered-list">
        {% for alt in alternatives[:8] %}
        <div class="k3-considered-card" data-netuid="{{ alt.netuid }}" onclick="switchToSubnet('{{ alt.netuid }}')">
          <div class="k3-considered-avatar">{{ alt.name|default('SN')|first|upper }}</div>
          <div class="k3-considered-name">{{ alt.name|default('SN' ~ alt.netuid) }}</div>
          {% if alt.role %}
          <div class="k3-considered-role">{{ alt.role }}</div>
          {% endif %}
          {% if alt.conviction is defined %}
          <div class="k3-considered-confidence">{{ '%.0f'|format(alt.conviction|float) }}%</div>
          {% endif %}
          {% set stance = alt.stance|default('HOLD')|upper %}
          <span class="k3-considered-stance k3-considered-stance--{{ stance|lower }}">
            {% if stance == 'LONG' %}BUY{% elif stance == 'SHORT' %}SELL{% else %}HOLD{% endif %}
          </span>
        </div>
        {% endfor %}
      </div>
    </div>
    {% else %}
    <div class="k3-empty">
      <div class="k3-empty-icon">⚖️</div>
      <div class="k3-empty-text">Council deliberation data warming up. Alternative subnet shortlist will appear here as the council weighs multiple candidates.</div>
    </div>
    {% endif %}
  </div>
</div>
```

### 3. JavaScript — Add `switchToSubnet()` in the `<script>` block

Add at the end of the script block (before `</script>`):

```javascript
// K3-2: Deliberation — switch context to alternative subnet
function switchToSubnet(netuid) {
  const url = new URL(window.location.href);
  url.searchParams.set('netuid', netuid);
  window.location.href = url.toString();
}
```

## Constraints

- Preserve ALL existing content — only add, never delete or modify existing Jinja/CSS/JS.
- Use 2-space indentation matching the file's existing style.
- Use `{# .... #}` Jinja comments for section markers.
- Do not change any existing IDs — live-refresh JS depends on them.
- The file currently ends with `</script>` and no trailing newline — preserve that.

## After editing

1. Verify the file with `git diff` — only the three insertions should appear
2. Commit with message: `feat: add K3-2 deliberation flow with considered subnet cards`
3. Push to a branch called `cursor/k3-2-deliberation`
4. Open a draft PR titled "K3-2: Council considered deliberation flow"
5. PR body should include the summary section from this spec
