import { useEffect, useState } from "react";
import { useI18n } from "../../i18n";

// In-fiction filler shown while a GM stream is in flight but no tokens have
// landed yet. Rotates every 2.5s so the wait doesn't feel frozen. Phrases are
// deliberately diegetic (rulebooks, NPCs, dice) — that keeps the player in
// the world instead of staring at a "loading..." spinner.
const HINTS_ZH = [
  "GM 正在翻规则书……",
  "NPC 正在暗中谋划……",
  "骰子还在桌面上滚动……",
  "卷宗在抽屉深处翻动……",
  "灯下的钢笔还没落下……",
  "GM 在地图上比划路线……",
  "远处传来一阵脚步声……",
  "墨水正在纸面晕开……",
  "命运的线还没缠紧……",
  "茶杯里的茶还没凉透……",
];

const HINTS_EN = [
  "GM is flipping through the rulebook…",
  "An NPC is plotting in the shadows…",
  "Dice are still tumbling across the table…",
  "Dossiers are being shuffled in the drawer…",
  "The pen hasn't quite touched the page…",
  "GM is tracing a route on the map…",
  "Footsteps echo somewhere down the hall…",
  "Ink is bleeding into the paper…",
  "The thread of fate hasn't pulled taut…",
  "The tea hasn't gone cold yet…",
];

const HINTS_JA = [
  "GM がルールブックをめくっています……",
  "NPC が陰で何かを企んでいます……",
  "サイコロがまだテーブルの上を転がっています……",
  "書類が引き出しの奥でかき混ぜられています……",
  "ペン先がまだ紙に触れていません……",
  "GM が地図の上で道筋を辿っています……",
  "遠くから足音が響いてきます……",
  "インクが紙にじんでいます……",
  "運命の糸はまだ張りつめていません……",
  "茶碗の中のお茶はまだ冷めていません……",
];

const HINTS_DE = [
  "Der Spielleiter blättert im Regelwerk …",
  "Ein NSC heckt im Verborgenen etwas aus …",
  "Die Würfel rollen noch über den Tisch …",
  "Akten werden tief in der Schublade durchwühlt …",
  "Die Feder hat das Papier noch nicht berührt …",
  "Der Spielleiter zeichnet eine Route auf der Karte nach …",
  "Schritte hallen irgendwo im Gang …",
  "Die Tinte verläuft auf dem Papier …",
  "Der Faden des Schicksals ist noch nicht gespannt …",
  "Der Tee in der Tasse ist noch nicht kalt …",
];

const HINTS_FR = [
  "Le MJ feuillette le manuel des règles…",
  "Un PNJ trame quelque chose dans l'ombre…",
  "Les dés roulent encore sur la table…",
  "On fouille des dossiers au fond du tiroir…",
  "La plume n'a pas encore touché le papier…",
  "Le MJ trace un itinéraire sur la carte…",
  "Des pas résonnent au loin dans le couloir…",
  "L'encre s'étale lentement sur la page…",
  "Le fil du destin ne s'est pas encore tendu…",
  "Le thé dans la tasse n'a pas encore refroidi…",
];

const HINTS_ES = [
  "El DJ está hojeando el manual de reglas…",
  "Un PNJ trama algo en las sombras…",
  "Los dados siguen rodando sobre la mesa…",
  "Se revuelven expedientes en el fondo del cajón…",
  "La pluma aún no ha tocado el papel…",
  "El DJ está trazando una ruta en el mapa…",
  "Pasos resuenan en algún lugar del pasillo…",
  "La tinta se esparce sobre la hoja…",
  "El hilo del destino aún no se ha tensado…",
  "El té de la taza aún no se ha enfriado…",
];

const HINTS_RU = [
  "Мастер листает книгу правил…",
  "НИП плетёт интригу в тени…",
  "Кости всё ещё катятся по столу…",
  "В глубине ящика шуршат старые папки…",
  "Перо ещё не коснулось бумаги…",
  "Мастер прокладывает маршрут на карте…",
  "Где-то в коридоре слышны шаги…",
  "Чернила медленно расплываются по бумаге…",
  "Нить судьбы ещё не натянулась…",
  "Чай в чашке ещё не остыл…",
];

const HINTS_BY_LOCALE: Record<string, string[]> = {
  zh: HINTS_ZH,
  en: HINTS_EN,
  ja: HINTS_JA,
  de: HINTS_DE,
  fr: HINTS_FR,
  es: HINTS_ES,
  ru: HINTS_RU,
};

function pickPool(locale: string): string[] {
  return HINTS_BY_LOCALE[locale] ?? HINTS_EN;
}

interface Props {
  className?: string;
}

export function WaitingHint({ className }: Props) {
  const { locale } = useI18n();
  const pool = pickPool(locale);
  const [idx, setIdx] = useState(() => Math.floor(Math.random() * pool.length));
  useEffect(() => {
    const id = window.setInterval(() => {
      setIdx((prev) => {
        if (pool.length <= 1) return prev;
        let next = Math.floor(Math.random() * pool.length);
        if (next === prev) next = (next + 1) % pool.length;
        return next;
      });
    }, 2500);
    return () => window.clearInterval(id);
  }, [pool.length]);
  const phrase = pool[idx % pool.length];
  return (
    <span
      className={[
        "inline-flex items-center gap-2 text-[12px] text-text-3 italic",
        "anim-fade-in",
        className || "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <Dot delay={0} />
      <Dot delay={0.15} />
      <Dot delay={0.3} />
      <span key={phrase}>{phrase}</span>
    </span>
  );
}

function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="inline-block w-1 h-1 rounded-full bg-text-3"
      style={{
        animation: "chatrpg-dot-bounce 1.2s ease-in-out infinite",
        animationDelay: `${delay}s`,
      }}
    />
  );
}
