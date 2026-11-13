export function PageHeading({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h1 className="text-4xl tracking-tight">{title}</h1>
      <p className="mt-3 max-w-prose text-label">{description}</p>
    </div>
  )
}
