interface PlaceholderPageProps {
  title: string;
  description: string;
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <section className="placeholder-page">
      <p className="eyebrow">WorkBrain MVP</p>
      <h1>{title}</h1>
      <p>{description}</p>
      <div className="placeholder-panel">
        <span>WorkBrain 企业工作台</span>
        <strong>请从主导航进入知识库、IT 服务或审批页面。</strong>
      </div>
    </section>
  );
}
