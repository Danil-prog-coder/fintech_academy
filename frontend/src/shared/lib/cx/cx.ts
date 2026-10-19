type ClassValue = string | false | null | undefined;

/** Склеивает имена классов, отбрасывая пустые значения. */
export const cx = (...values: ClassValue[]): string => values.filter(Boolean).join(' ');
