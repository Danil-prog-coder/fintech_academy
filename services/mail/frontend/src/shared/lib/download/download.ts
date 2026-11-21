const escapeCsvCell = (value: string) => `"${value.replaceAll('"', '""')}"`;

/** Формирует CSV (с BOM для Excel) и отдаёт его пользователю как файл. */
export const downloadCsv = (fileName: string, rows: string[][]) => {
  const content = rows.map((row) => row.map(escapeCsvCell).join(';')).join('\n');
  const blob = new Blob(['﻿', content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
};
