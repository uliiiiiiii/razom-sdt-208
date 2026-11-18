// Lucide icons via Iconify, rendered to inline SVG.
// Bundled on purpose: the API's content security policy blocks the Iconify CDN.
import { iconToHTML, iconToSVG } from "@iconify/utils";
import map from "@iconify-icons/lucide/map";
import plus from "@iconify-icons/lucide/plus";
import search from "@iconify-icons/lucide/search";
import locate from "@iconify-icons/lucide/locate-fixed";
import logout from "@iconify-icons/lucide/log-out";
import x from "@iconify-icons/lucide/x";
import zap from "@iconify-icons/lucide/zap";
import bag from "@iconify-icons/lucide/shopping-bag";
import pill from "@iconify-icons/lucide/pill";
import droplet from "@iconify-icons/lucide/droplet";
import car from "@iconify-icons/lucide/car";
import paw from "@iconify-icons/lucide/paw-print";
import ellipsis from "@iconify-icons/lucide/ellipsis";
import pin from "@iconify-icons/lucide/map-pin";
import house from "@iconify-icons/lucide/house";
import help from "@iconify-icons/lucide/hand-helping";
import building from "@iconify-icons/lucide/building-2";
import lock from "@iconify-icons/lucide/lock";
import chevron from "@iconify-icons/lucide/chevron-left";
import user from "@iconify-icons/lucide/user-round";
import clock from "@iconify-icons/lucide/clock";
import sun from "@iconify-icons/lucide/sun";
import moon from "@iconify-icons/lucide/moon";

const ICONS = {
  map,
  plus,
  search,
  locate,
  logout,
  x,
  zap,
  bag,
  pill,
  droplet,
  car,
  paw,
  ellipsis,
  pin,
  house,
  help,
  building,
  lock,
  chevron,
  user,
  clock,
  sun,
  moon,
};

export function icon(name, size = 18) {
  const data = ICONS[name];
  if (!data) return "";
  const built = iconToSVG(data, { width: size, height: size });
  return iconToHTML(built.body, {
    ...built.attributes,
    class: "ico",
    "aria-hidden": "true",
  });
}
