const areas = [
  ["Investigation", "Start og følg en kildebevisst undersøkelse."],
  ["Graph", "Utforsk personer, virksomheter og dokumenterte relasjoner."],
  ["Evidence", "Se hva som faktisk støtter eller motsier hver påstand."],
  ["Report", "Bygg en rapport fra verifiserte claims, ikke søkesnutter."],
];

export default function Home() {
  return (
    <main>
      <header>
        <p className="eyebrow">ANALYSEN</p>
        <h1>Norsk OSINT med sporbar evidens.</h1>
        <p className="lead">
          Primærkilder først. Konservativ identitetsmatching. Alle vesentlige funn tilbake til kilden.
        </p>
      </header>
      <section className="grid">
        {areas.map(([title, text]) => (
          <article key={title}>
            <h2>{title}</h2>
            <p>{text}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
