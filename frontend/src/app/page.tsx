import { redirect } from "next/navigation";

/* La entrada al sistema es el perfil, no el extractor.
 *
 * Hasta v2.5 la raíz redirigía a /upload, así que se entraba directo a subir un
 * PDF y las páginas de perfil, plan y sesión quedaban inalcanzables aunque
 * existieran. Subir material es una acción DENTRO del perfil de alguien, no el
 * punto de partida: sin saber quién sube, el documento no puede sumarse a
 * ningún plan ni alimentar ningún perfil cognitivo. */

export default function Home() {
  redirect("/estudiantes");
}
