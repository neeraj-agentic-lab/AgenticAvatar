import AvatarSession from "@/components/AvatarSession";

export default function Home() {
  return (
    <main style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", gap: "1.5rem" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>AgenticAvatar</h1>
      <AvatarSession />
    </main>
  );
}
