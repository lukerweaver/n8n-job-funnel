export function moneyRange(min: number | null, max: number | null) {
  if (min === null && max === null) {
    return "N/A";
  }
  const formatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
  if (min !== null && max !== null) {
    return `${formatter.format(min)} - ${formatter.format(max)}`;
  }
  return formatter.format((min ?? max) as number);
}

export function formatDate(value: string | null) {
  if (!value) {
    return "N/A";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatDateOnly(value: string | null) {
  if (!value) {
    return "N/A";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

export function renderListish(value: unknown) {
  if (value == null) {
    return "N/A";
  }
  if (Array.isArray(value)) {
    return value.join(", ") || "N/A";
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}
