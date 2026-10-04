import type { ButtonHTMLAttributes } from "react";

/** Native button semantics, a 48px target, and a visible keyboard focus ring. */
export function Button({
  type = "button",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} type={type} className={`button ${className}`.trim()} />;
}
