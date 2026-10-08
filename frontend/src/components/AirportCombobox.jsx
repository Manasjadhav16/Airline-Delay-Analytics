import { useEffect, useId, useMemo, useRef, useState } from "react";
import { airportLabel, shortName } from "../airportLabels";
import "./AirportCombobox.css";

// Lowercase, drop accents and punctuation so "o'hare", "ohare" and "O'Hare"
// all match the same airport.
function normalize(text) {
  return (text ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9 ]+/g, "");
}

function place(airport) {
  return [airport.city, airport.state].filter(Boolean).join(", ");
}

/**
 * Searchable airport picker. `value` and `onChange` deal only in IATA codes;
 * labels are display-only. Typing filters the list but never changes the
 * value -- only picking an option does -- so the form always holds a code
 * the model knows.
 */
export default function AirportCombobox({ id, value, airports, popular, onChange }) {
  const listId = useId();
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const byCode = useMemo(() => new Map(airports.map((a) => [a.code, a])), [airports]);
  const selected = byCode.get(value);

  const indexed = useMemo(
    () =>
      airports.map((a) => ({
        airport: a,
        code: a.code.toLowerCase(),
        haystack: normalize(`${a.code} ${a.name} ${a.city} ${a.state}`),
      })),
    [airports]
  );

  // Groups shown in the list. Empty query: popular first (by volume), then
  // every airport A-Z by name. With a query: one ranked list of matches.
  const groups = useMemo(() => {
    const q = normalize(query).trim();
    if (!q) {
      const popularRows = popular.map((code) => byCode.get(code)).filter(Boolean);
      const all = [...airports].sort((a, b) =>
        (a.name ?? a.code).localeCompare(b.name ?? b.code)
      );
      return [
        ...(popularRows.length ? [{ label: "Popular airports", items: popularRows }] : []),
        { label: "All airports", items: all },
      ];
    }

    const tokens = q.split(/\s+/);
    const popularRank = new Map(popular.map((code, i) => [code, i]));
    const matches = indexed
      .filter((row) => tokens.every((t) => row.haystack.includes(t)))
      .map((row) => {
        let rank = 3;
        if (row.code === q) rank = 0;
        else if (row.code.startsWith(q)) rank = 1;
        else if (popularRank.has(row.airport.code)) rank = 2;
        return { ...row, rank };
      })
      .sort(
        (a, b) =>
          a.rank - b.rank ||
          (popularRank.get(a.airport.code) ?? Infinity) -
            (popularRank.get(b.airport.code) ?? Infinity) ||
          (a.airport.name ?? a.airport.code).localeCompare(b.airport.name ?? b.airport.code)
      )
      .map((row) => row.airport);
    return [{ label: `${matches.length} matching`, items: matches }];
  }, [query, airports, popular, byCode, indexed]);

  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open]);

  function openList() {
    setOpen(true);
    setQuery("");
    // Start on the current airport when it's in the popular group.
    const start = popular.indexOf(value);
    setActiveIndex(start >= 0 ? start : 0);
  }

  function close() {
    setOpen(false);
    setQuery("");
  }

  function choose(airport) {
    onChange(airport.code);
    close();
  }

  function handleKeyDown(e) {
    if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      openList();
      return;
    }
    if (!open) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActiveIndex(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActiveIndex(flat.length - 1);
    } else if (e.key === "Enter") {
      // Don't submit the form while picking.
      e.preventDefault();
      if (flat[activeIndex]) choose(flat[activeIndex]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "Tab") {
      close();
    }
  }

  let optionIndex = -1;
  const activeId = open && flat[activeIndex] ? `${listId}-opt-${activeIndex}` : undefined;

  return (
    <div className="combo">
      <input
        ref={inputRef}
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={activeId}
        autoComplete="off"
        spellCheck={false}
        placeholder="Search code, airport or city"
        value={open ? query : airportLabel(selected)}
        title={open ? undefined : airportLabel(selected)}
        onFocus={openList}
        onClick={() => !open && openList()}
        onBlur={close}
        onChange={(e) => {
          setQuery(e.target.value);
          setActiveIndex(0);
          if (!open) setOpen(true);
        }}
        onKeyDown={handleKeyDown}
      />
      {open && (
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="Airports"
          className="combo-list"
          // Keep focus in the input so blur doesn't close before the click lands.
          onMouseDown={(e) => e.preventDefault()}
        >
          {flat.length === 0 && (
            <div className="combo-empty">No airport matches “{query}”.</div>
          )}
          {groups.map((group) =>
            group.items.length === 0 ? null : (
              <div key={group.label} role="group" aria-label={group.label}>
                <div className="combo-group board-label" aria-hidden="true">
                  {group.label}
                </div>
                {group.items.map((airport) => {
                  optionIndex += 1;
                  const index = optionIndex;
                  return (
                    <div
                      key={`${group.label}-${airport.code}`}
                      id={`${listId}-opt-${index}`}
                      data-index={index}
                      role="option"
                      aria-selected={airport.code === value}
                      className={`combo-option ${index === activeIndex ? "is-active" : ""} ${
                        airport.code === value ? "is-selected" : ""
                      }`}
                      onMouseMove={() => index !== activeIndex && setActiveIndex(index)}
                      onClick={() => choose(airport)}
                    >
                      <span className="combo-code">{airport.code}</span>
                      <span className="combo-text">
                        <span className="combo-name">
                          {shortName(airport.name) ?? "Name not in airports.csv"}
                        </span>
                        {place(airport) && <span className="combo-place">{place(airport)}</span>}
                      </span>
                    </div>
                  );
                })}
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}
