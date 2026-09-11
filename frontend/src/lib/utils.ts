import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Merge class lists so a caller's `className` wins over a component's
 *  own defaults instead of both landing in the class attribute and the
 *  cascade deciding at random. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
