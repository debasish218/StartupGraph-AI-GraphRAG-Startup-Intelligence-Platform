export function JsonView({ value, className }: { value: unknown; className?: string }) {
  let text: string;
  try {
    text = JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  return <pre className={`json ${className ?? ''}`}>{text}</pre>;
}
