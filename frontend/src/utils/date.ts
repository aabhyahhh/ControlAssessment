/** Formats an ISO 'YYYY-MM-DD' date string as 'DD/MM/YYYY'. Returns the
 *  input unchanged if it isn't a full ISO date (e.g. already partial/empty)
 *  rather than producing a misleading reformat of the wrong thing. */
export function formatDateDMY(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!match) return isoDate;
  const [, year, month, day] = match;
  return `${day}/${month}/${year}`;
}

const MONTH_ABBR = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** Formats a 'YYYY-MM' month string as 'Mon YYYY' (e.g. "Dec 2024") — there
 *  is no day component, so DD/MM/YYYY doesn't apply to these. */
export function formatMonthYear(yearMonth: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(yearMonth);
  if (!match) return yearMonth;
  const [, year, month] = match;
  const idx = Number(month) - 1;
  return idx >= 0 && idx < 12 ? `${MONTH_ABBR[idx]} ${year}` : yearMonth;
}

/** Compact 'Mon 'YY' form (e.g. "Dec '24") for dense column headers — a
 *  full "Mon YYYY" label doesn't fit a narrow grid column at any font size
 *  once a period spans a dozen-plus months, so this trades a couple of
 *  digits of precision for actually fitting on one line. */
export function formatMonthYearShort(yearMonth: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(yearMonth);
  if (!match) return yearMonth;
  const [, year, month] = match;
  const idx = Number(month) - 1;
  return idx >= 0 && idx < 12 ? `${MONTH_ABBR[idx]} '${year.slice(2)}` : yearMonth;
}
