import { useWheelhouseText, type MessageKey } from "./i18n";

// The three notes under a chart, always expanded.
export function ReadColumns({
  shows,
  implies,
  how,
}: {
  shows: MessageKey;
  implies: MessageKey;
  how: MessageKey;
}) {
  const { text } = useWheelhouseText();
  return (
    <div className="wh-seller-read">
      {(
        [
          ["seller.read.shows", shows],
          ["seller.read.implies", implies],
          ["seller.read.how", how],
        ] as const
      ).map(([heading, body]) => (
        <div key={heading}>
          <h4>{text(heading)}</h4>
          <p>{text(body)}</p>
        </div>
      ))}
    </div>
  );
}
