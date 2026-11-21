/** Содержимое файла в base64 (без префикса data:). */
export const fileToBase64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      resolve(result.slice(result.indexOf(',') + 1));
    };
    reader.onerror = () => {
      reject(new Error(`Не удалось прочитать файл ${file.name}.`));
    };
    reader.readAsDataURL(file);
  });

const EMAIL_RE = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/;

export const splitAddresses = (value: string): string[] =>
  value
    .split(/[,;\s]+/)
    .map((part) => part.trim())
    .filter(Boolean);

export const invalidAddresses = (list: string[]): string[] =>
  list.filter((email) => !EMAIL_RE.test(email));
