import { Bebas_Neue, IBM_Plex_Mono, Inter_Tight } from "next/font/google";

/* The card faces (globals.css: font-bebas / font-plex / font-tight).
   One module, because two places need the variables: the studio layout,
   and every dialog -- Base UI portals a dialog to <body>, outside the
   layout's wrapper, where the variables would otherwise be undefined and
   the drawer would fall back to Impact. Studio only: the landing page does
   not pay for three faces it never sets. */
const bebas = Bebas_Neue({ variable: "--font-bebas-neue", subsets: ["latin"], weight: "400" });
const plex = IBM_Plex_Mono({ variable: "--font-plex-mono", subsets: ["latin"], weight: ["400", "500"] });
const tight = Inter_Tight({ variable: "--font-inter-tight", subsets: ["latin"], weight: ["400", "500", "600"] });

export const cardFonts = `${bebas.variable} ${plex.variable} ${tight.variable}`;
