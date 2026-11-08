import { registerRoot, Composition } from "remotion";
import { Podcast } from "./Podcast";

registerRoot(() => {
  return (
    <Composition
      id="Podcast"
      component={Podcast}
      durationInFrames={13330}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{
        title: "Demo",
        chapters: [],
      }}
      calculateMetadata={({ props }) => {
        const last = props.chapters[props.chapters.length - 1];
        return { durationInFrames: Math.ceil((last ? last.end : 0) * 30) + 90 };
      }}
    />
  );
});
