# [FSD 아키텍처]: 레이어 단방향 의존성 및 상위 슬라이스 직접 참조 금지

- **분류**: `frontend_architecture`
- **도메인**: `fullstack_web`
- **주제**: `FSD (Feature-Sliced Design)`
- **제목**: `레이어 단방향 의존성 규칙 및 Cross-Slice 결합 방지`
- **우선순위**: `critical`

## 규칙 개요
Feature-Sliced Design(FSD)에서 계층(Layer)은 다음과 같이 엄격한 하향식 단방향 의존성을 가져야 합니다:
`app` -> `pages` -> `widgets` -> `features` -> `entities` -> `shared`

1. **상위 레이어 역참조 금지**: 하위 레이어(`entities`, `shared`)는 절대로 상위 레이어(`features`, `widgets`, `pages`)를 import할 수 없습니다.
2. **동일 레이어 Cross-Slice 직접 참조 금지**: 같은 레이어 내의 슬라이스 간(예: `entities/user`가 `entities/order`를 직접 import) 직접 결합을 금지하며, 상위 레이어(`features`나 `widgets`)에서 합성하거나 슬롯(Slot/children)으로 주입해야 합니다.

---

### ❌ Anti-Pattern (Bad)

```typescript
// entities/user/ui/UserProfileCard.tsx
// [결함]: 하위 레이어(entities)가 상위 레이어(features)의 비즈니스 UI 컴포넌트를 직접 import함.
// 결과: 순환 참조 위험 발생 및 entities 계층의 독립적 재사용성 파괴.
import { EditProfileModal } from '@/features/edit-profile/ui/EditProfileModal';
import { User } from '../model/types';

interface Props {
  user: User;
}

export function UserProfileCard({ user }: Props) {
  return (
    <div className="card">
      <h3>{user.name}</h3>
      <p>{user.email}</p>
      {/* 엔티티 카드 내부에 상위 피처 모달이 강결합됨 */}
      <EditProfileModal userId={user.id} />
    </div>
  );
}
```

---

### ✅ Best Practice (Good)

```typescript
// entities/user/ui/UserProfileCard.tsx
// [모범]: 하위 레이어는 순수한 데이터 표현만 담당하고, 액션이나 상위 UI는 슬롯(ReactNode)으로 주입받음.
// 결과: entities 레이어의 순수성 유지 및 단방향 의존성 보장.
import { ReactNode } from 'react';
import { User } from '../model/types';

interface Props {
  user: User;
  actionSlot?: ReactNode;
}

export function UserProfileCard({ user, actionSlot }: Props) {
  return (
    <div className="card">
      <h3>{user.name}</h3>
      <p>{user.email}</p>
      {actionSlot && <div className="card-actions">{actionSlot}</div>}
    </div>
  );
}

// widgets/user-profile/ui/UserProfileWidget.tsx
// [상위 위젯에서 합성]: widgets 계층에서 entities와 features를 가져와 결합함.
import { UserProfileCard } from '@/entities/user';
import { EditProfileModal } from '@/features/edit-profile';

export function UserProfileWidget({ user }: { user: User }) {
  return (
    <UserProfileCard
      user={user}
      actionSlot={<EditProfileModal userId={user.id} />}
    />
  );
}
```
