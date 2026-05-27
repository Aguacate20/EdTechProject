import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EdTech Scaffolding",
  description: "Plataforma de aprendizaje con gamificación",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
