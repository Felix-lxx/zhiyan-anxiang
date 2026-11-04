/** Group nearby hit targets on compact maps without altering stored coordinates. */
export function groupMapMarkers<T extends { id: string; geometry: { x: number; y: number } }>(
  objects: T[], width: number, height: number, compact: boolean, selectedId: string | null,
): Array<{ object: T; members: T[] }> {
  if (!compact || width <= 0 || height <= 0) return objects.map(object => ({ object, members: [object] }))
  const parents = objects.map((_, index) => index)
  const root = (index: number): number => {
    while (parents[index] !== index) { parents[index] = parents[parents[index]!]!; index = parents[index]! }
    return index
  }
  for (let i = 0; i < objects.length; i++) {
    for (let j = i + 1; j < objects.length; j++) {
      const a = objects[i]!, b = objects[j]!
      if (Math.abs(a.geometry.x - b.geometry.x) * width / 100 < 48 &&
          Math.abs(a.geometry.y - b.geometry.y) * height / 100 < 48) parents[root(j)] = root(i)
    }
  }
  const groups = new Map<number, T[]>()
  objects.forEach((object, index) => {
    const key = root(index), members = groups.get(key) ?? []
    members.push(object); groups.set(key, members)
  })
  return [...groups.values()].map(members => ({ object: members.find(item => item.id === selectedId) ?? members[0]!, members }))
}
