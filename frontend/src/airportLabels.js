// Display labels for airports. Values sent to the API stay plain IATA codes.

// "Chicago O'Hare International Airport" -> "Chicago O'Hare International";
// the code already says it's an airport.
export function shortName(name) {
  return name ? name.replace(/\s+Airport$/i, "") : null;
}

// "ORD – Chicago O'Hare International", or just the code when the lookup
// has no name for it.
export function airportLabel(airport) {
  if (!airport) return "";
  const name = shortName(airport.name);
  return name ? `${airport.code} – ${name}` : airport.code;
}
